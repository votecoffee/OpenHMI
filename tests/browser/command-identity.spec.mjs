import { test, expect } from '@playwright/test';

test('command sources cannot replace retained transactions or unlock runtime dispatch', async ({ page }) => {
  test.setTimeout(90000);
  const errors = [], activations = [];
  page.on('pageerror', error => errors.push(error.message));
  const original = await (await page.request.get('/api/project')).json();
  async function install(project) {
    const state = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
    expect(saved.ok()).toBe(true);
    expect((await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } })).ok()).toBe(true);
  }
  const project = structuredClone(original.active);
  project.tags.push({ name: 'IdentityCommand', type: 'struct', writable: true,
    initial: { RequestSequence: 0, AcceptedSequence: 0, CompletedSequence: 0, ResultCode: 0, Permit: true },
    members: { RequestSequence: 'integer', AcceptedSequence: 'integer', CompletedSequence: 'integer', ResultCode: 'integer', Permit: 'boolean' } });
  project.commands = [{ id: 'identity_cycle', name: 'Identity cycle', root_tag: 'IdentityCommand', permit_member: 'Permit', timeout_seconds: 60 }];
  project.controls.push({ id: 'identity_request', kind: 'button', label: 'Request identity cycle', mode: 'command', command: 'identity_cycle' },
    { id: 'identity_complete', kind: 'button', label: 'Complete fixture cycle', action: 'identity_complete' });
  let history, detail;
  try {
    await install(project);
    await page.goto('/runtime');
    const request = page.getByRole('button', { name: 'Request identity cycle', exact: true });
    const control = page.locator('[data-control="button"]').filter({ has: request });
    await expect(request).toBeEnabled();
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/controls/identity_request/activate') activations.push(request.url());
    });
    await request.click();
    await expect(control).toContainText('PLC command: requested');
    const link = control.getByRole('link', { name: /^View command transaction #/ });
    const href = await link.getAttribute('href');
    const id = Number(new URL(href, page.url()).searchParams.get('transaction'));
    history = await page.context().newPage();
    detail = await page.context().newPage();
    await history.goto('/commands');
    await detail.goto(href);
    const historyRows = history.locator('.activity-table tbody');
    const detailRows = detail.locator('.activity-table tbody');
    await expect(historyRows).toContainText('identity_cycle');
    await expect(detailRows).toContainText('requested');
    await history.getByLabel('Command ID', { exact: true }).fill('Retained unapplied filter');
    let mode = 'foreign';
    const intercept = async route => {
      if (mode === 'same') return route.continue();
      if (mode === 'denied') return route.fulfill({ status: 403, body: 'Forbidden', contentType: 'text/plain' });
      const response = await route.fetch();
      const value = await response.json();
      const changed = record => ({ ...record, state: 'completed', result_code: 0, error: 'FOREIGN COMPLETION' });
      const body = JSON.stringify(value.items ? { ...value, items: value.items.map(changed) } : changed(value));
      const headers = { ...response.headers() };
      delete headers['content-length'];
      if (mode === 'missing') delete headers['x-openhmi-project'];
      else headers['x-openhmi-project'] = 'f'.repeat(32);
      return route.fulfill({ response, headers, body });
    };
    for (const tab of [page, history, detail]) {
      await tab.route('**/api/commands?*', intercept);
      await tab.route(`**/api/commands/${id}`, intercept);
    }
    for (const failure of ['foreign', 'missing']) {
      mode = failure;
      await expect(control).toContainText('Command status unavailable');
      await expect(request).toBeDisabled();
      await expect(control).toContainText('PLC command: requested');
      await expect(link).toHaveAttribute('href', href);
      for (const tab of [history, detail]) {
        await expect(tab.getByRole('alert')).toContainText('Showing last received command status');
        await expect(tab.locator('.activity-table tbody')).toContainText('requested');
        await expect(tab.locator('body')).not.toContainText('FOREIGN COMPLETION');
      }
      await expect(history.getByRole('button', { name: 'Older commands', exact: true })).toBeDisabled();
      mode = 'same';
      await expect(control).not.toContainText('Command status unavailable');
      await expect(request).toBeDisabled(); // The confirmed transaction is still requested.
      await expect(history.getByRole('alert')).toHaveCount(0);
      await expect(detail.getByRole('alert')).toHaveCount(0);
    }
    await expect(history.getByLabel('Command ID', { exact: true })).toHaveValue('Retained unapplied filter');
    expect(activations).toHaveLength(1);
    mode = 'denied';
    await expect(control).toContainText('Command status unavailable');
    await expect(link).toHaveCount(0);
    await expect(request).toBeDisabled();
    await expect(historyRows.locator('tr')).toHaveCount(0);
    await expect(detailRows.locator('tr')).toHaveCount(0);
    mode = 'foreign';
    await expect(detail.getByRole('alert')).toContainText('A different project is open');
    await expect(control.getByRole('link')).toHaveCount(0); // A foreign completion cannot restore denied evidence.
    await expect(request).toBeDisabled();
    await page.getByRole('button', { name: 'Complete fixture cycle', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get(`/api/commands/${id}`)).json()).state).toBe('completed');
    await expect(request).toBeDisabled(); // Real completion also waits for a matching-source read.
    mode = 'same';
    await expect(control).toContainText('PLC command: completed');
    await expect(request).toBeEnabled();
    await expect(historyRows).toContainText('completed');
    await expect(detailRows).toContainText('completed');
    await expect(link).toHaveAttribute('href', href);
    expect(activations).toHaveLength(1);
    expect((await (await page.request.get('/api/tags')).json()).values['IdentityCommand.RequestSequence']).toBe(1);
    expect(errors).toEqual([]);
  } finally {
    await history?.close(); await detail?.close();
    await install(original.active);
    const state = await (await page.request.get('/api/project')).json();
    await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project: original.draft } });
  }
});
