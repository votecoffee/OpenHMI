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
  await expect(observer.getByText('PLC connections are held. Review the project and use Apply live to enable its configured connections.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open HMI login', exact: true }).first()).toBeVisible();
  await expect(page.getByText('PLC connections are held. Review the project and use Apply live to enable its configured connections.')).toBeVisible();
  await login();
  await expect(page.getByRole('button', { name: 'Apply live', exact: true })).toBeVisible();
  await page.goto('/projects');
  await page.getByRole('button', { name: 'Open BrowserMachine.openhmi.sqlite3', exact: true }).click();
  await login();
  await expect(page.locator('.station-title h1')).toContainText('Browser machine');
});
