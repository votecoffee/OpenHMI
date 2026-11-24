import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8766' });

async function initialize(page) {
  const login = await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
  expect(login.ok()).toBe(true);
  return (await (await page.request.get('/api/project')).json()).project_instance;
}

function replyFor(mode, source, data, foreign) {
  if (mode === 'denied') return { status: 403, body: 'Forbidden', contentType: 'text/plain' };
  return { headers: mode === 'missing' ? {} : { 'X-OpenHMI-Project': mode === 'same' ? source : 'f'.repeat(32) },
    json: mode === 'same' ? data : foreign(data) };
}

test('activity source failures retain only the current page and recover older reads without operator replay', async ({ page }) => {
  test.setTimeout(90000);
  const source = await initialize(page);
  const errors = [], writes = [];
  page.on('pageerror', error => errors.push(error.message));
  // Two local fixture actions return the motor to its original state and seed real journal rows.
  for (let i = 0; i < 2; i++) expect((await page.request.post('/api/controls/toggle/activate', { data: {} })).ok()).toBe(true);
  const newest = await (await page.request.get('/api/activity?search=toggle&limit=1')).json();
  const older = await (await page.request.get(`/api/activity?search=toggle&limit=1&before_id=${newest.next_before_id}`)).json();
  expect(newest.has_more).toBe(true);
  expect(older.items).toHaveLength(1);
  let mode = 'same';
  await page.route('**/api/activity?*', route => {
    const data = new URL(route.request().url()).searchParams.has('before_id') ? older : newest;
    return route.fulfill(replyFor(mode, source, data, page => ({ ...page,
      items: page.items.map(row => ({ ...row, actor: 'FOREIGN OPERATOR' })) })));
  });
  page.on('request', request => {
    if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/controls/')) writes.push(request.url());
  });
  await page.goto('/activity?search=toggle');
  const panel = page.getByRole('region', { name: 'Operator activity', exact: true });
  const rows = panel.locator('.activity-table tbody');
  const warning = panel.getByRole('alert');
  const olderButton = panel.getByRole('button', { name: 'Older activity', exact: true });
  const filter = panel.getByLabel('Control, tag or operation ID', { exact: true });
  await expect(rows).toContainText(newest.items[0].operation_id);
  await filter.fill('Retained unapplied activity filter');
  for (const failure of ['foreign', 'missing']) {
    mode = failure;
    await expect(warning).toContainText('Showing last received activity', { timeout: 8000 });
    await expect(rows).toContainText(newest.items[0].operation_id);
    await expect(panel).not.toContainText('FOREIGN OPERATOR');
    await expect(olderButton).toBeDisabled();
    mode = 'same';
    await panel.getByRole('button', { name: 'Newest activity', exact: true }).click();
    await expect(warning).toHaveCount(0);
    await expect(olderButton).toBeEnabled();
  }
  mode = 'denied';
  await expect(warning).toContainText('HTTP 403', { timeout: 8000 });
  await expect(rows.locator('tr')).toHaveCount(0);
  mode = 'same';
  await panel.getByRole('button', { name: 'Newest activity', exact: true }).click();
  await expect(olderButton).toBeEnabled();
  mode = 'foreign';
  await olderButton.click();
  await expect(warning).toContainText('A different project is open');
  await expect(warning).not.toContainText('Showing last received activity');
  await expect(rows.locator('tr')).toHaveCount(0);
  mode = 'same';
  await expect(rows).toContainText(older.items[0].operation_id, { timeout: 8000 });
  await expect(rows).not.toContainText(newest.items[0].operation_id);
  await expect(warning).toHaveCount(0);
  await expect(filter).toHaveValue('Retained unapplied activity filter');
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test('diagnostics source failures retain quality and workers only for the current filter and offset', async ({ page }) => {
  test.setTimeout(60000);
  const source = await initialize(page);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const first = await (await page.request.get('/api/diagnostics?offset=0&limit=1')).json();
  const second = await (await page.request.get('/api/diagnostics?offset=1&limit=1')).json();
  expect(first.next_offset).toBe(1);
  let mode = 'same';
  await page.route('**/api/diagnostics?*', route => {
    const data = new URL(route.request().url()).searchParams.get('offset') === '1' ? second : first;
    return route.fulfill(replyFor(mode, source, data, snapshot => ({ ...snapshot,
      tags: snapshot.tags.map(tag => ({ ...tag, name: 'FOREIGN TAG', quality: 'good', error: 'FOREIGN QUALITY' })),
      workers: snapshot.workers.map(worker => ({ ...worker, id: 'FOREIGN WORKER' })) })));
  });
  await page.goto('/diagnostics');
  const panel = page.getByRole('region', { name: 'Runtime diagnostics', exact: true });
  const rows = panel.locator('.diagnostics-tags tbody');
  const workers = panel.getByRole('table', { name: 'Runtime workers', exact: true });
  const warning = panel.getByRole('alert');
  const more = panel.getByRole('button', { name: 'More tags', exact: true });
  const filter = panel.getByLabel('Tag filter', { exact: true });
  await expect(rows).toContainText(first.tags[0].name);
  await expect(workers).toBeVisible();
  await filter.fill('Retained unapplied diagnostic filter');
  for (const failure of ['foreign', 'missing']) {
    mode = failure;
    await expect(warning).toContainText('Showing last received diagnostics');
    await expect(rows).toContainText(first.tags[0].name);
    await expect(workers).toBeVisible();
    await expect(panel).not.toContainText('FOREIGN');
    await expect(more).toBeDisabled();
    mode = 'same';
    await expect(warning).toHaveCount(0);
    await expect(more).toBeEnabled();
  }
  mode = 'denied';
  await expect(warning).toContainText('HTTP 403');
  await expect(rows.locator('tr')).toHaveCount(0);
  await expect(workers).toHaveCount(0);
  mode = 'same';
  await expect(more).toBeEnabled();
  mode = 'foreign';
  await more.click();
  await expect(warning).toContainText('A different project is open');
  await expect(warning).not.toContainText('Showing last received diagnostics');
  await expect(rows.locator('tr')).toHaveCount(0);
  mode = 'same';
  await expect(rows).toContainText(second.tags[0].name);
  await expect(rows).not.toContainText(first.tags[0].name);
  await expect(filter).toHaveValue('Retained unapplied diagnostic filter');
  await expect(warning).toHaveCount(0);
  expect(errors).toEqual([]);
});
