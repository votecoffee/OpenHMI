import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8766' });
test('touch entry, colored lock legend, login popup and explicit PLC identity station', async ({ page }) => {
  test.setTimeout(90000);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/runtime');
  async function login(name) {
    await page.getByRole('button', { name: 'Open HMI login', exact: true }).first().click();
    const dialog = page.getByRole('dialog', { name: 'HMI login', exact: true });
    await dialog.getByLabel('HMI user', { exact: true }).fill(name);
    await dialog.getByLabel('HMI password', { exact: true }).fill('SecurityTestOnly-2026!');
    await dialog.getByRole('button', { name: 'Sign in to HMI', exact: true }).click();
    await expect(dialog).not.toBeVisible();
  }
  await login('admin');
  let version = (await (await page.request.get('/api/security')).json()).version;
  for (const fields of [{ operation: 'group', name: 'TouchOperators', permissions: ['runtime.write', 'runtime.operate', 'identity.publish'], color: '#527d80' }, { operation: 'user', name: 'touch_operator', password: 'SecurityTestOnly-2026!', groups: ['TouchOperators'] }]) {
    const response = await page.request.put('/api/security', { data: { ...fields, expected_version: version, reason: 'Synthetic touch fixture' } });
    expect(response.ok()).toBe(true); version = (await response.json()).version;
  }
  const original = await (await page.request.get('/api/project')).json();
  async function install(project) {
    const current = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { project, expected_revision: current.draft_revision } }); expect(saved.ok()).toBe(true);
    const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } }); expect(applied.ok()).toBe(true);
  }
  const project = structuredClone(original.active);
  project.tags.push({ name: 'TouchLow', type: 'number', initial: 10, writable: true }, { name: 'TouchHigh', type: 'number', initial: 50, writable: true }, { name: 'LoginName', type: 'string', initial: '', writable: true }, { name: 'LoginBits', type: 'integer', initial: 0, writable: true });
  project.controls.push({ id: 'touch_number', kind: 'input', label: 'Touch number', tag: 'TankLevel', minimum_tag: 'TouchLow', maximum_tag: 'TouchHigh', security_groups: ['TouchOperators'] }, { id: 'touch_text', kind: 'text_input', label: 'Touch text', tag: 'OperatorText', min_length: 1, max_length: 4, security_groups: ['TouchOperators'] }, { id: 'who', kind: 'current_user', label: 'Operator login' });
  project.identity_publication = { enabled: true, username_tag: 'LoginName', privileges_tag: 'LoginBits', username_bytes: 82, bits: [{ bit: 0, source: 'permission', name: 'runtime.operate' }, { bit: 3, source: 'group', name: 'TouchOperators' }] };
  try {
    await install(project); await page.reload();
    await page.getByRole('button', { name: 'Sign out of HMI', exact: true }).click();
    await page.getByRole('button', { name: 'Locked: Touch number', exact: true }).click();
    const legend = page.getByRole('dialog', { name: 'Security group legend', exact: true });
    await expect(legend).toContainText('TouchOperators');
    await expect(legend.locator('.security-swatch')).toHaveCSS('background-color', 'rgb(82, 125, 128)');
    await legend.getByRole('button', { name: 'Close Security group legend', exact: true }).click();
    await login('touch_operator');
    await expect(page.locator('[data-control="current_user"]')).toContainText('touch_operator');
    await page.getByRole('button', { name: 'Open numeric keypad for Touch number', exact: true }).click();
    const numeric = page.getByRole('dialog', { name: 'Numeric entry: Touch number', exact: true });
    await numeric.getByLabel('Entry', { exact: true }).fill('55');
    await numeric.getByRole('button', { name: 'Accept entry', exact: true }).click();
    await expect(numeric.getByRole('alert')).toContainText('Allowed range');
    await numeric.getByRole('button', { name: 'Clear', exact: true }).click();
    await numeric.getByRole('button', { name: '2', exact: true }).click(); await numeric.getByRole('button', { name: '5', exact: true }).click();
    await numeric.getByRole('button', { name: 'Accept entry', exact: true }).click();
    await expect(numeric).not.toBeVisible();
    await expect(page.locator('[data-control="input"]').filter({ hasText: 'Touch number' })).toContainText('25.0');
    await page.getByRole('button', { name: 'Open keyboard for Touch text', exact: true }).click();
    const text = page.getByRole('dialog', { name: 'Text entry: Touch text', exact: true });
    await text.getByRole('button', { name: 'a', exact: true }).click(); await text.getByRole('button', { name: 'b', exact: true }).click();
    if (process.env.OPENHMI_TOUCH_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_TOUCH_SCREENSHOT, fullPage: true });
    await text.getByRole('button', { name: 'Accept entry', exact: true }).click();
    await expect(page.locator('[data-control="text_input"]')).toContainText('ab');
    await page.getByRole('button', { name: 'Publish this station login', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LoginName).toBe('touch_operator');
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LoginBits).toBe(9);
    await page.getByRole('button', { name: 'Sign out of HMI', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LoginBits).toBe(0);
    expect(errors).toEqual([]);
  } finally {
    await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
    const current = await (await page.request.get('/api/project')).json();
    if (current.active.identity_publication.enabled) { const disabled = structuredClone(current.active); disabled.identity_publication.enabled = false; await install(disabled); await expect.poll(async () => (await (await page.request.get('/api/security/publication')).json()).status).toBe('disabled'); }
    await install(original.active);
    const restored = await (await page.request.get('/api/project')).json();
    await page.request.put('/api/project/draft', { data: { project: original.draft, expected_revision: restored.draft_revision } });
  }
});
