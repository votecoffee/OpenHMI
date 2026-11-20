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
