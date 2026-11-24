import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8766' });

async function signIn(page) {
  const login = await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
  expect(login.ok()).toBe(true);
  return (await page.request.get('/api/project')).json();
}

test('foreign or missing runtime identities never replace values alarms or signed-in user and matching reads recover', async ({ page }) => {
  const original = await signIn(page);
  const source = original.project_instance;
  const foreign = 'f'.repeat(32);
  const tags = await (await page.request.get('/api/tags')).json();
  const alarms = await (await page.request.get('/api/alarms')).json();
  const identity = await (await page.request.get('/api/security/session')).json();
  const active = await (await page.request.get('/api/project/active')).json();
  let mode = 'same';
  const headers = () => mode === 'missing' ? {} : { 'X-OpenHMI-Project': mode === 'same' ? source : foreign };
  await page.route('**/api/project/active', route => route.fulfill({ headers: { 'X-OpenHMI-Project': source }, json: active }));
  await page.route('**/api/tags', route => route.fulfill({ headers: headers(), json: mode === 'same' ? tags : {
    ...tags, values: { ...tags.values, TankLevel: 9876.5 }, samples: { ...tags.samples, TankLevel: { value: 9876.5, quality: 'good' } } } }));
  await page.route('**/api/alarms', route => route.fulfill({ headers: headers(), json: mode === 'same' ? alarms : {
    ...alarms, active_count: 1, unacknowledged_count: 1,
    outstanding: [{ occurrence_id: 987, priority: 1, message: 'FOREIGN ALARM', active: true, quality: 'good' }],
    annunciated_outstanding: [{ occurrence_id: 987, priority: 1, message: 'FOREIGN ALARM', active: true, quality: 'good' }],
    annunciated_active_count: 1, annunciated_unacknowledged_count: 1 } }));
  await page.route('**/api/security/session', route => route.fulfill({ headers: headers(), json: mode === 'same' ? identity : {
    ...identity, user: { ...identity.user, name: 'FOREIGN USER' } } }));
  await page.goto('/runtime');
  const numeric = page.locator('[data-control="numeric"]');
  const banner = page.getByLabel('Screen alarm status');
  const bar = page.locator('.security-bar');
  const warning = page.getByText('HMI identity status unavailable.', { exact: false });
  await expect(numeric).toContainText(tags.values.TankLevel.toFixed(1));
  await expect(bar).toContainText('Signed in: admin');
  for (const next of ['foreign', 'missing']) {
    mode = next;
    await expect(numeric).toContainText('COMM LOSS');
    await expect(banner).toContainText('ALARM MONITOR UNAVAILABLE');
    await expect(warning).toBeVisible();
    await expect(bar).toContainText('Signed in: admin');
    await expect(page.locator('body')).not.toContainText('FOREIGN USER');
    await expect(page.locator('body')).not.toContainText('FOREIGN ALARM');
    await expect(numeric).not.toContainText('9876.5');
    mode = 'same';
    await expect(numeric).toContainText(tags.values.TankLevel.toFixed(1));
    await expect(warning).toBeHidden();
  }
});

test('editor detects a foreign applied project without adopting its connection metadata or draft', async ({ page }) => {
  const original = await signIn(page);
  const active = await (await page.request.get('/api/project/active')).json();
  let changed = false;
  const foreign = { ...active, project_instance: 'e'.repeat(32), revision: active.revision + 1,
    project: { ...active.project, title: 'FOREIGN EDITOR PROJECT', connections: [{ id: 'foreign', name: 'FOREIGN ROUTE', enabled: true }] } };
  await page.route('**/api/project/active', route => route.fulfill({ headers: { 'X-OpenHMI-Project': changed ? foreign.project_instance : original.project_instance }, json: changed ? foreign : active }));
  await page.goto('/');
  const header = page.locator('.app-header .connection');
  await expect(header).toContainText('Simulator connected');
  await page.locator('[data-control="numeric"]').click();
  await page.getByRole('textbox', { name: 'Label', exact: true }).fill('Retained original project draft');
  await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
  changed = true;
  await expect(page.getByText('A different project was opened.', { exact: false })).toBeVisible();
  await expect(header).toContainText('Simulator connected');
  await expect(page.locator('body')).not.toContainText('FOREIGN ROUTE');
  await expect(page.getByRole('textbox', { name: 'Label', exact: true })).toHaveValue('Retained original project draft');
  expect(page.url()).not.toContain('/runtime');
  // Restore the synthetic draft for other scenarios using the shared test server.
  const state = await (await page.request.get('/api/project')).json();
  expect((await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project: original.draft } })).ok()).toBe(true);
});

test('real project switch reloads the runtime and pins the replacement only on fresh initialization', async ({ page }) => {
  const original = await signIn(page);
  await page.goto('/runtime');
  await expect(page.locator('[data-control="numeric"]')).toContainText('42.0');
  const created = await page.request.post('/api/workspace/create', { data: { name: 'IdentitySwitch', title: 'Replacement identity fixture' } });
  expect(created.ok()).toBe(true);
  const initialized = page.waitForResponse(async response => new URL(response.url()).pathname === '/api/project'
    && response.ok() && response.headers()['x-openhmi-project'] !== original.project_instance);
  const opened = await page.request.post('/api/workspace/open', { data: { file: 'IdentitySwitch.openhmi.sqlite3' } });
  expect(opened.ok()).toBe(true);
  const replacement = await initialized;
  const source = replacement.headers()['x-openhmi-project'];
  expect(source).not.toBe(original.project_instance);
  expect((await replacement.json()).project_instance).toBe(source);
  await page.waitForRequest(request => new URL(request.url()).pathname === '/api/tags'
    && request.headers()['x-openhmi-project'] === source);
  await expect(page.locator('[data-control="numeric"]')).toContainText('42.0');
  expect(page.url()).toContain('/runtime');
});

test('initial catalog from another project cannot initialize a mixed editor', async ({ page }) => {
  await signIn(page);
  await page.route('**/api/catalog', async route => {
    const response = await route.fetch();
    return route.fulfill({ response, headers: { ...response.headers(), 'x-openhmi-project': 'd'.repeat(32) } });
  });
  await page.goto('/');
  await expect(page.locator('#root')).toContainText('Unable to open project: A different project is open.');
  await expect(page.locator('[data-control]')).toHaveCount(0);
});
