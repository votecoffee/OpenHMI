import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8766' });

test('a stale operator button cannot dispatch a replacement action', async ({ page }) => {
  const login = await page.request.post('/api/security/login', {
    data: { name: 'admin', password: 'SecurityTestOnly-2026!' },
  });
  expect(login.ok()).toBe(true);
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const state = await (await page.request.get('/api/project')).json();
    const draft = await page.request.put('/api/project/draft', { data: { project, expected_revision: state.draft_revision } });
    expect(draft.ok(), await draft.text()).toBe(true);
    if (apply) expect((await page.request.post('/api/project/apply', {
      data: { expected_revision: (await draft.json()).draft_revision },
    })).ok()).toBe(true);
  }

  try {
    await page.goto('/runtime');
    const stale = page.getByRole('button', { name: 'Toggle simulated motor', exact: true });
    await expect(stale).toBeEnabled();
    const oldMotor = (await (await page.request.get('/api/tags')).json()).values.MotorRunning;
    const displayed = await (await page.request.get('/api/project/active')).json();
    const activeEndpoint = '**/api/project/active';
    await page.route(activeEndpoint, route => route.fulfill({ json: displayed }));
    const project = structuredClone(original.active);
    project.tags.push({ name: 'ButtonTarget', type: 'boolean', initial: false, writable: true });
    Object.assign(project.controls.find(control => control.id === 'toggle'),
      { label: 'Set replacement target', mode: 'set', target: 'ButtonTarget', value: true });
    await save(project);
    const [result] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/controls/toggle/activate')),
      stale.click(),
    ]);
    expect(result.status()).toBe(409);
    expect(result.headers()['x-openhmi-audit-status']).toBe('rejected');
    await expect(page.getByText('The applied project changed. Review the updated button before trying again.')).toBeVisible();
    const values = (await (await page.request.get('/api/tags')).json()).values;
    expect(values.MotorRunning).toBe(oldMotor);
    expect(values.ButtonTarget).toBe(false);

    await page.unroute(activeEndpoint);
    await page.getByRole('button', { name: 'Set replacement target', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.ButtonTarget).toBe(true);
  } finally {
    await save(original.active);
    await save(original.draft, false);
  }
});

test('diagnostics keeps readable results through bad polls and clears them on denied access', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const login = await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
  expect(login.ok()).toBe(true);
  const snapshot = await (await page.request.get('/api/diagnostics')).json();
  const healthy = { json: { ...snapshot, total_tags: 101, next_offset: 100 } };
  let reply = healthy;
  await page.route('**/api/diagnostics?*', route => reply ? route.fulfill(reply) : route.continue());
  await page.goto('/diagnostics');
  const panel = page.getByRole('region', { name: 'Runtime diagnostics', exact: true });
  const warning = panel.getByRole('alert');
  const rows = panel.locator('.diagnostics-tags tbody');
  await expect(rows).toContainText('TankLevel');

  for (const invalid of [{}, { ...snapshot, tags: [null] },
    { ...snapshot, workers: [{ ...snapshot.workers[0], state: 'overdue', running_seconds: null }] }]) {
    reply = { json: invalid };
    await expect(warning).toContainText('Showing last received diagnostics');
    await expect(rows).toContainText('TankLevel');
    await expect(panel.getByRole('button', { name: 'More tags' })).toBeDisabled();
    reply = healthy;
    await expect(warning).toBeHidden();
    await expect(panel.getByRole('button', { name: 'More tags' })).toBeEnabled();
  }

  reply = { status: 503, json: { detail: 'Synthetic diagnostics outage' } };
  await expect(warning).toContainText('Showing last received diagnostics');
  await panel.getByLabel('Tag filter').fill('MotorRunning');
  await panel.getByRole('button', { name: 'Filter diagnostic tags' }).click();
  await expect(warning).toContainText('Synthetic diagnostics outage');
  await expect(warning).not.toContainText('Showing last received diagnostics');
  await expect(rows.locator('tr')).toHaveCount(0);
  reply = undefined;
  await expect(rows).toContainText('MotorRunning');
  await expect(rows).not.toContainText('TankLevel');
  await expect(warning).toBeHidden();

  reply = { status: 403, body: 'Forbidden', contentType: 'text/plain' };
  await expect(warning).toContainText('HTTP 403');
  await expect(rows.locator('tr')).toHaveCount(0);
  reply = undefined;
  await expect(rows).toContainText('MotorRunning');
  await expect(warning).toBeHidden();
  expect(errors).toEqual([]);
});

test('activity preserves the current page through malformed replies and retries an older page', async ({ page }) => {
  test.setTimeout(60000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const login = await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
  expect(login.ok()).toBe(true);
  const journal = await (await page.request.get('/api/activity')).json();
  const stamp = '2026-01-01T00:00:00+00:00';
  const entry = { id: 2, operation_id: 'newer-record', started_at: stamp, finished_at: stamp,
    actor: 'admin', provider: 'local', groups: ['Administrators'], operation: 'button_action', entity: 'toggle',
    phase: 'finalized', status: 'succeeded', context: {}, outcome: null, error: null };
  const newest = { ...journal, items: [entry], has_more: true, next_before_id: 2 };
  const older = { ...journal, items: [{ ...entry, id: 1, operation_id: 'older-record' }], has_more: false, next_before_id: null };
  let reply = { json: newest };
  let olderReply = { status: 503, json: { detail: 'Synthetic older page outage' } };
  await page.route('**/api/activity?*', route => route.fulfill(new URL(route.request().url()).searchParams.has('before_id') ? olderReply : reply));
  await page.goto('/activity');
  const panel = page.getByRole('region', { name: 'Operator activity', exact: true });
  const warning = panel.getByRole('alert');
  const rows = panel.locator('.activity-table tbody');
  const olderButton = panel.getByRole('button', { name: 'Older activity', exact: true });
  await expect(rows).toContainText('newer-record');
  await expect(olderButton).toBeEnabled();

  reply = { json: { ...newest, items: [{ ...entry, groups: {} }] } };
  await expect(warning).toContainText('Showing last received activity', { timeout: 8000 });
  await expect(rows).toContainText('newer-record');
  await expect(olderButton).toBeDisabled();
  reply = { status: 403, body: 'Forbidden', contentType: 'text/plain' };
  await expect(warning).toContainText('HTTP 403', { timeout: 8000 });
  await expect(rows.locator('tr')).toHaveCount(0);
  reply = { json: newest };
  await expect(olderButton).toBeEnabled({ timeout: 8000 });

  await olderButton.click();
  await expect(warning).toContainText('Synthetic older page outage');
  await expect(rows.locator('tr')).toHaveCount(0);
  olderReply = { json: older };
  await expect(rows).toContainText('older-record', { timeout: 8000 });
  await expect(warning).toBeHidden();
  expect(errors).toEqual([]);
});

test('protected operator journal, denial attribution, filters, export and diagnostics', async ({ page }) => {
  test.setTimeout(120000);
  const errors = [];
  const originalMotor = (await (await page.request.get('/api/tags')).json()).values.MotorRunning;
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/activity');
  await expect(page.getByText('Sign in with activity viewing permission to inspect the operator journal.')).toBeVisible();
  await page.getByRole('button', { name: 'Open HMI login', exact: true }).first().click();
  await page.getByLabel('HMI user', { exact: true }).fill('admin');
  await page.getByLabel('HMI password', { exact: true }).fill('SecurityTestOnly-2026!');
  await page.getByRole('button', { name: 'Sign in to HMI', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Operator activity', exact: true })).toBeVisible();
  const activeLease = after => page.waitForResponse(response => {
    const request = response.request();
    if (!request.url().endsWith('/api/subscriptions') || request.method() !== 'POST') return false;
    const body = request.postDataJSON();
    return body.screens.includes('overview') && (!after || body.client === after.client && body.sequence > after.sequence);
  });
  const releasedLease = lease => page.waitForResponse(response => {
    const request = response.request();
    if (!request.url().endsWith('/api/subscriptions') || request.method() !== 'POST') return false;
    const body = request.postDataJSON();
    return body.client === lease.client && !body.screens.length && body.sequence > lease.sequence;
  });
  const initialLease = activeLease();
  await page.goto('/runtime');
  const initial = (await initialLease).request().postDataJSON();
  const hidden = releasedLease(initial);
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })));
  const hiddenResponse = await hidden;
  expect(hiddenResponse.ok()).toBe(true);
  const restored = activeLease(hiddenResponse.request().postDataJSON());
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
  const restoredResponse = await restored;
  expect(restoredResponse.ok()).toBe(true);

  await page.getByRole('button', { name: 'Toggle simulated motor', exact: true }).click();
  await page.getByRole('link', { name: 'Activity', exact: true }).click();
  const successful = page.locator('.activity-table tbody tr').filter({ hasText: 'toggle' }).first();
  await expect(successful).toContainText('admin');
  await expect(successful).toContainText('succeeded');
  await successful.getByText('Operation details', { exact: true }).click();
  await expect(successful).toContainText('callback_returned');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export activity CSV', exact: true }).click();
  expect((await downloadPromise).suggestedFilename()).toBe('operator-activity.csv');
  await page.getByRole('button', { name: 'Sign out of HMI', exact: true }).click();
  const denied = await page.request.post('/api/controls/toggle/activate', { data: {} });
  expect(denied.status()).toBe(401);
  expect(denied.headers()['x-openhmi-audit-status']).toBe('denied');
  await page.getByRole('button', { name: 'Open HMI login', exact: true }).first().click();
  await page.getByLabel('HMI user', { exact: true }).fill('admin');
  await page.getByLabel('HMI password', { exact: true }).fill('SecurityTestOnly-2026!');
  await page.getByRole('button', { name: 'Sign in to HMI', exact: true }).click();
  await page.getByRole('combobox', { name: 'Outcome', exact: true }).selectOption('denied');
  await page.getByRole('button', { name: 'Apply activity filters', exact: true }).click();
  await expect(page.locator('.activity-table tbody tr').first()).toContainText('anonymous');
  await expect(page.locator('.activity-table tbody tr').first()).toContainText('denied');
  if (process.env.OPENHMI_ACTIVITY_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_ACTIVITY_SCREENSHOT, fullPage: true });
  const noScan = page.waitForRequest(request => request.url().endsWith('/api/subscriptions') && request.method() === 'POST' && request.postDataJSON().screens.length === 0);
  await page.getByRole('link', { name: 'Diagnostics', exact: true }).click();
  await noScan;
  await expect(page.getByRole('region', { name: 'Runtime diagnostics', exact: true })).toBeVisible();
  const workers = page.getByRole('table', { name: 'Runtime workers', exact: true });
  await expect(workers.getByRole('row').filter({ hasText: 'Historian' })).toContainText('healthy');
  await page.getByLabel('Tag filter', { exact: true }).fill('TankLevel');
  await page.getByRole('button', { name: 'Filter diagnostic tags', exact: true }).click();
  await expect(page.locator('.diagnostics-tags tbody tr')).toHaveCount(1);
  await expect(page.locator('.diagnostics-tags tbody tr')).toContainText('good');
  await expect(page.getByText('No PLC connections are configured.')).toBeVisible();
  const quality = page.getByRole('combobox', { name: 'Sample quality', exact: true });
  const applyFilter = page.getByRole('button', { name: 'Filter diagnostic tags', exact: true });
  await quality.selectOption('non-good');
  await applyFilter.click();
  await expect(page.getByText('0 matching logical tags.', { exact: false })).toBeVisible();
  await expect(page.locator('.diagnostics-tags tbody tr')).toHaveCount(0);
  await quality.selectOption('good');
  await applyFilter.click();
  await expect(page.locator('.diagnostics-tags tbody tr')).toHaveCount(1);
  await expect(page.getByRole('link', { name: 'Export diagnostics JSON', exact: true })).toHaveAttribute('href', '/api/diagnostics.json?search=TankLevel&quality=good');
  const jsonDownload = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export diagnostics JSON', exact: true }).click();
  expect((await jsonDownload).suggestedFilename()).toBe('runtime-diagnostics.json');
  if (process.env.OPENHMI_DIAGNOSTICS_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_DIAGNOSTICS_SCREENSHOT, fullPage: true });
  await page.route('**/api/diagnostics?*', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.connections = [{
      id: 'bench', name: 'Bench PLC', path: 'offline-only/0', state: 'scan overdue', scan_age_seconds: 6,
      read_calls: 8, tags_read: 12, groups: [], route_failures: 1,
      timings: Object.fromEntries(Object.entries({
        recovery: 1375, scan_queue: 1, route_lock_wait: 150, adapter_read: 12,
      }).map(([key, ms]) => [key, { last_ms: ms, p50_ms: ms, p95_ms: ms, p99_ms: ms, count: 1 }])),
    }];
    await route.fulfill({ response, json: data });
  });
  const bench = page.getByRole('row').filter({ hasText: 'Bench PLC' });
  await bench.getByText('Timing (ms)', { exact: true }).click();
  await expect(bench.getByText('Loss to first good read', { exact: true })).toBeVisible();
  await expect(bench).toContainText('p95 1375');
  for (const label of ['Scan worker queue', 'Route lock wait', 'Adapter read call']) {
    await expect(bench.getByText(label, { exact: true })).toBeVisible();
  }
  await expect(bench).toContainText('Route failures: 1');
  await expect(bench).toContainText('6.0 s in flight');
  expect(errors).toEqual([]);
  if ((await (await page.request.get('/api/tags')).json()).values.MotorRunning !== originalMotor) {
    expect((await page.request.post('/api/controls/toggle/activate', { data: {} })).ok()).toBe(true);
  }
});
