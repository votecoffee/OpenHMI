import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test.use({ baseURL: 'http://127.0.0.1:8766' });
test('project library creates, opens, exports and imports a complete backup', async ({ page }, info) => {
  test.setTimeout(120000);
  async function login() {
    await page.getByRole('button', { name: 'Open HMI login', exact: true }).first().click();
    await page.getByLabel('HMI user', { exact: true }).fill('admin');
    await page.getByLabel('HMI password', { exact: true }).fill('SecurityTestOnly-2026!');
    await page.getByRole('button', { name: 'Sign in to HMI', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Sign out of HMI', exact: true })).toBeVisible();
  }
  await page.goto('/projects');
  await login();
  await page.getByLabel('New project ID', { exact: true }).fill('BrowserMachine');
  await page.getByLabel('New project title', { exact: true }).fill('Browser machine');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open BrowserMachine.openhmi.sqlite3', exact: true })).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export complete backup', exact: true }).click();
  const download = await downloadPromise;
  const path = info.outputPath('synthetic-project.openhmi.zip');
  await download.saveAs(path);
  await page.getByLabel('Imported project ID', { exact: true }).fill('BrowserRestore');
  await page.getByLabel('OpenHMI backup ZIP', { exact: true }).setInputFiles({ name: 'synthetic-project.openhmi.zip', mimeType: 'application/zip', buffer: await readFile(path) });
  await page.getByRole('button', { name: 'Import complete backup', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open BrowserRestore.openhmi.sqlite3', exact: true })).toBeVisible();
  const observer = await page.context().newPage();
  await observer.goto('/runtime');
  await expect(observer.locator('.station-title h1')).toBeVisible();
  const reloaded = observer.waitForEvent('framenavigated', { predicate: frame => frame === observer.mainFrame() });
  await page.getByRole('button', { name: 'Open BrowserRestore.openhmi.sqlite3', exact: true }).click();
  await reloaded;
  await page.waitForURL('http://127.0.0.1:8766/');
  await expect(observer.getByText('PLC connections are held. Review the project and use Apply live to enable its configured connections.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open HMI login', exact: true }).first()).toBeVisible();
  await expect(page.getByText('PLC connections are held. Review the project and use Apply live to enable its configured connections.')).toBeVisible();
  await login();
  await expect(page.getByRole('button', { name: 'Apply live', exact: true })).toBeVisible();
  await page.goto('/projects');
  await page.getByRole('button', { name: 'Open BrowserMachine.openhmi.sqlite3', exact: true }).click();
  await page.waitForURL('http://127.0.0.1:8766/');
  await login();
  await expect(page.locator('.station-title h1')).toContainText('Browser machine');
});


test('file inventory retains confirmed metadata on malformed replies, clears denial and recovers', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const signedIn = await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
  expect(signedIn.ok()).toBe(true);
  const first = { items: [{ file: 'Retained.openhmi.hold', project_file: 'Retained.openhmi.sqlite3', kind: 'connection_hold',
    entry_type: 'file', project_entry_type: 'missing', size_bytes: 24 }], next_after: 'Retained.openhmi.hold', scan_limited: false };
  let reply = { json: first };
  const requests = [];
  await page.route('**/api/workspace/artifacts*', route => {
    requests.push({ method: route.request().method(), url: route.request().url() });
    return route.fulfill(reply);
  });
  await page.goto('/projects');
  const panel = page.getByRole('region', { name: 'Project file inventory', exact: true });
  const rows = panel.locator('tbody');
  await expect(rows).toContainText('Retained.openhmi.hold');
  await expect(rows).toContainText('No database present');
  await page.getByLabel('New project ID', { exact: true }).fill('KeepMyDraft');
  reply = { json: { items: [null], next_after: null, scan_limited: false } };
  await panel.getByRole('button', { name: 'Next files', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('Showing the last confirmed file inventory');
  await expect(rows).toContainText('Retained.openhmi.hold');
  await expect(panel.getByRole('button', { name: 'Next files', exact: true })).toBeDisabled();
  expect(new URL(requests.at(-1).url).searchParams.get('after')).toBe(first.next_after);
  reply = { json: { ...first, scan_limited: true } };
  await panel.getByRole('button', { name: 'Refresh file inventory', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('directory scan was limited');
  await expect(rows).toContainText('Retained.openhmi.hold');
  reply = { status: 403, json: { detail: 'Synthetic permission denial' } };
  await panel.getByRole('button', { name: 'Refresh file inventory', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('File inventory unavailable');
  await expect(panel.locator('tbody')).toHaveCount(0);
  reply = { json: first };
  await panel.getByRole('button', { name: 'Refresh file inventory', exact: true }).click();
  await expect(rows).toContainText('Retained.openhmi.hold');
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await expect(page.getByLabel('New project ID', { exact: true })).toHaveValue('KeepMyDraft');
  expect(requests.every(request => request.method === 'GET')).toBe(true);
  expect(errors).toEqual([]);
});


async function signedInLibrary(page) {
  const response = await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
  expect(response.ok()).toBe(true);
  const current = await (await page.request.get('/api/workspace')).json();
  return { ...current, projects: [{ file: current.current, current: true }, { file: 'ReviewTarget.openhmi.sqlite3', current: false }] };
}

test('project listing faults retain draft fields, block operations, clear denial and recover', async ({ page }) => {
  test.setTimeout(60000);
  const snapshot = await signedInLibrary(page);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let reply = { json: snapshot };
  let mutations = 0;
  await page.route('**/api/workspace', route => route.fulfill(reply));
  await page.route('**/api/workspace/create', route => { mutations++; return route.fulfill({ status: 500 }); });
  await page.route('**/api/workspace/import?*', route => { mutations++; return route.fulfill({ status: 500 }); });
  await page.goto('/projects');
  const library = page.getByRole('region', { name: 'Project library', exact: true });
  const name = page.getByLabel('New project ID', { exact: true });
  const title = page.getByLabel('New project title', { exact: true });
  const imported = page.getByLabel('Imported project ID', { exact: true });
  await name.fill('KeepDraft'); await title.fill('Keep this title'); await imported.fill('KeepImport');
  await page.getByLabel('OpenHMI backup ZIP', { exact: true }).setInputFiles({ name: 'kept.zip', mimeType: 'application/zip', buffer: Buffer.from('synthetic selected backup') });
  expect(mutations).toBe(0);
  reply = { json: { ...snapshot, projects: [null] } };
  await library.getByRole('button', { name: 'Refresh projects', exact: true }).click();
  await expect(page.getByRole('alert', { name: 'Project library availability', exact: true })).toContainText('last confirmed project library');
  await expect(name).toHaveValue('KeepDraft'); await expect(title).toHaveValue('Keep this title'); await expect(imported).toHaveValue('KeepImport');
  await expect(page.getByText('Selected backup: kept.zip', { exact: true })).toBeVisible();
  await expect(library.getByRole('button', { name: 'Create project', exact: true })).toBeDisabled();
  await expect(library.getByRole('button', { name: 'Import complete backup', exact: true })).toBeDisabled();
  await expect(library.getByRole('button', { name: 'Open ReviewTarget.openhmi.sqlite3', exact: true })).toBeDisabled();
  await expect(library.getByRole('link', { name: 'Export complete backup', exact: true })).toHaveCount(0);
  reply = { json: snapshot };
  await library.getByRole('button', { name: 'Refresh projects', exact: true }).click();
  await expect(library.getByRole('button', { name: 'Create project', exact: true })).toBeEnabled();
  reply = { status: 403, json: { detail: 'Synthetic denial' } };
  await library.getByRole('button', { name: 'Refresh projects', exact: true }).click();
  await expect(page.getByRole('alert', { name: 'Project library availability', exact: true })).toContainText('Project library unavailable');
  await expect(library.getByRole('button', { name: 'Open ReviewTarget.openhmi.sqlite3', exact: true })).toHaveCount(0);
  reply = { json: snapshot };
  await library.getByRole('button', { name: 'Refresh projects', exact: true }).click();
  await expect(name).toHaveValue('KeepDraft'); await expect(imported).toHaveValue('KeepImport');
  await expect(page.getByText('Selected backup: kept.zip', { exact: true })).toBeVisible();
  expect(mutations).toBe(0); expect(errors).toEqual([]);
});

test('ambiguous create and open acknowledgements preserve drafts and never replay or redirect', async ({ page }) => {
  test.setTimeout(60000);
  const snapshot = await signedInLibrary(page);
  await page.route('**/api/workspace', route => route.fulfill({ json: snapshot }));
  let created = 0, opened = 0;
  let receipt = { file: 'Wrong.openhmi.sqlite3' };
  await page.route('**/api/workspace/create', route => { created++; return route.fulfill({ json: receipt }); });
  await page.route('**/api/workspace/open', route => { opened++; return route.fulfill({ json: { ok: true, current: 'Wrong.openhmi.sqlite3' } }); });
  await page.goto('/projects');
  const name = page.getByLabel('New project ID', { exact: true });
  const title = page.getByLabel('New project title', { exact: true });
  await name.fill('AckGuard'); await title.fill('Retained title');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page.getByRole('alert', { name: 'Project operation', exact: true })).toContainText('may have completed');
  await expect(name).toHaveValue('AckGuard'); await expect(title).toHaveValue('Retained title');
  await expect(page.getByRole('button', { name: 'Create project', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Refresh projects', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Create project', exact: true })).toBeEnabled();
  expect(created).toBe(1);
  receipt = { file: 'AckGuard.openhmi.sqlite3' };
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(name).toHaveValue(''); await expect(title).toHaveValue('');
  await expect(page.getByRole('status', { name: 'Project operation', exact: true })).toContainText('Created AckGuard.openhmi.sqlite3');
  expect(created).toBe(2);
  await page.getByRole('button', { name: 'Open ReviewTarget.openhmi.sqlite3', exact: true }).click();
  await expect(page.getByRole('alert', { name: 'Project operation', exact: true })).toContainText('Refresh the project library');
  expect(page.url()).toContain('/projects'); expect(opened).toBe(1);
  await page.getByRole('button', { name: 'Refresh projects', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open ReviewTarget.openhmi.sqlite3', exact: true })).toBeEnabled();
  expect(opened).toBe(1);
});

test('import selection waits for explicit action and survives an ambiguous acknowledgement', async ({ page }) => {
  test.setTimeout(60000);
  const snapshot = await signedInLibrary(page);
  await page.route('**/api/workspace', route => route.fulfill({ json: snapshot }));
  const payload = Buffer.from('synthetic retained backup');
  const uploads = [];
  let held = false;
  await page.route('**/api/workspace/import?*', route => {
    uploads.push(route.request().postDataBuffer());
    return route.fulfill({ json: { file: 'ImportGuard.openhmi.sqlite3', handlers_saved_for_review: false, plc_hold: held } });
  });
  await page.goto('/projects');
  await page.getByLabel('Imported project ID', { exact: true }).fill('ImportGuard');
  await page.getByLabel('OpenHMI backup ZIP', { exact: true }).setInputFiles({ name: 'retained.zip', mimeType: 'application/zip', buffer: payload });
  await expect(page.getByText('Selected backup: retained.zip', { exact: true })).toBeVisible();
  expect(uploads).toHaveLength(0);
  const button = page.getByRole('button', { name: 'Import complete backup', exact: true });
  await button.click();
  await expect(page.getByRole('alert', { name: 'Project operation', exact: true })).toContainText('may have completed');
  await expect(page.getByText('Selected backup: retained.zip', { exact: true })).toBeVisible();
  await expect(button).toBeDisabled();
  await page.getByRole('button', { name: 'Refresh projects', exact: true }).click();
  await expect(button).toBeEnabled(); expect(uploads).toHaveLength(1);
  held = true;
  await button.click();
  await expect(page.getByRole('status', { name: 'Project operation', exact: true })).toContainText('Imported ImportGuard.openhmi.sqlite3');
  await expect(page.getByText('Selected backup: retained.zip', { exact: true })).toHaveCount(0);
  await expect(button).toBeDisabled();
  expect(uploads).toHaveLength(2);
  expect(uploads.every(bytes => bytes.equals(payload))).toBe(true);
});
