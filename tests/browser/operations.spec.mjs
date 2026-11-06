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
  await page.goto('/runtime');
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
  const jsonDownload = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export diagnostics JSON', exact: true }).click();
  expect((await jsonDownload).suggestedFilename()).toBe('runtime-diagnostics.json');
  if (process.env.OPENHMI_DIAGNOSTICS_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_DIAGNOSTICS_SCREENSHOT, fullPage: true });
  await page.route('**/api/diagnostics?*', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.connections = [{
      id: 'bench', name: 'Bench PLC', path: 'offline-only/0', state: 'connected',
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
  expect(errors).toEqual([]);
  if ((await (await page.request.get('/api/tags')).json()).values.MotorRunning !== originalMotor) {
    expect((await page.request.post('/api/controls/toggle/activate', { data: {} })).ok()).toBe(true);
  }
});
