import { test, expect } from '@playwright/test';

test('recipe refresh rejects foreign library and identity while preserving selected revision and unsaved content', async ({ page }) => {
  const errors = [], writes = [];
  page.on('pageerror', error => errors.push(error.message));
  const project = await (await page.request.get('/api/project')).json();
  const base = await (await page.request.get('/api/recipes')).json();
  const revision = number => ({ id: number, recipe_id: 1, number, version: 1, code: 'IDENTITY', status: 'draft',
    author: 'Original author', approved_by: null, approved_at: null,
    content: { title: `Original revision ${number}`, description: 'Original description', image_id: null, parameters: [] } });
  const library = { ...base, revisions: [revision(2), revision(1)], audit: [{ id: 1, recipe_id: 1, revision_id: 1,
    timestamp: '2026-01-01T00:00:00Z', actor: 'Original author', operation: 'created', details: { reason: 'Original audit reason' } }] };
  let libraryMode = 'foreign', sessionMode = 'same';
  const headers = mode => mode === 'missing' ? {} : { 'X-OpenHMI-Project': mode === 'same' ? project.project_instance : 'f'.repeat(32) };
  await page.route('**/api/recipes', route => {
    if (route.request().method() !== 'GET') { writes.push(route.request().url()); return route.continue(); }
    if (libraryMode === 'denied') return route.fulfill({ status: 403, body: 'Forbidden', contentType: 'text/plain' });
    return route.fulfill({ headers: headers(libraryMode), json: libraryMode === 'same' ? library : {
      ...library, revisions: library.revisions.map(item => ({ ...item, content: { ...item.content, title: 'FOREIGN RECIPE' } })) } });
  });
  await page.route('**/api/recipe-auth/session', async route => {
    const response = await route.fetch();
    const data = await response.json();
    return route.fulfill({ headers: headers(sessionMode), json: sessionMode === 'same' ? data : {
      configured: true, user: { name: 'FOREIGN USER', roles: ['administrator'] } } });
  });
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/recipes\/[^/]+\/revisions$/.test(new URL(request.url()).pathname)) writes.push(request.url());
  });
  await page.goto('/recipe-editor');
  await expect(page.getByRole('alert')).toContainText('A different project is open');
  await expect(page.getByLabel('Recipe title', { exact: true })).toHaveCount(0);
  libraryMode = 'same';
  await page.getByRole('button', { name: 'Retry recipe library', exact: true }).click();
  await page.getByLabel('Recipe user', { exact: true }).fill('engineer');
  await page.getByLabel('Password', { exact: true }).fill('RecipeTestOnly-2026!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.locator('.recipe-session')).toContainText('Signed in: engineer');
  const selected = page.getByLabel('Recipe revision', { exact: true });
  await selected.selectOption('1');
  const title = page.getByLabel('Recipe title', { exact: true });
  const description = page.getByRole('textbox', { name: /^Description/ });
  const reason = page.getByRole('textbox', { name: /^Change \/ approval \/ load reason/ });
  await title.fill('Retained unsaved revision');
  await description.fill('Retained description draft');
  await reason.fill('Retained change reason');
  const save = page.getByRole('button', { name: 'Save new revision', exact: true });
  const refresh = page.getByRole('button', { name: 'Refresh recipes', exact: true });
  await expect(save).toBeEnabled();
  for (const target of ['library', 'session']) {
    for (const mode of ['foreign', 'missing']) {
      if (target === 'library') libraryMode = mode; else sessionMode = mode;
      await refresh.click();
      await expect(page.getByRole('alert')).toContainText('Showing the last readable library');
      await expect(save).toBeDisabled();
      await expect(title).toBeDisabled();
      await expect(selected).toHaveValue('1');
      await expect(title).toHaveValue('Retained unsaved revision');
      await expect(description).toHaveValue('Retained description draft');
      await expect(reason).toHaveValue('Retained change reason');
      await expect(page.locator('.recipe-history')).toContainText('Original audit reason');
      await expect(page.locator('.recipe-session')).toContainText('Signed in: engineer');
      await expect(page.locator('body')).not.toContainText('FOREIGN');
      libraryMode = 'same'; sessionMode = 'same';
      await refresh.click();
      await expect(page.getByRole('alert')).toHaveCount(0);
      await expect(save).toBeEnabled();
    }
  }
  libraryMode = 'denied';
  await refresh.click();
  await expect(page.getByRole('alert')).toContainText('HTTP 403');
  await expect(save).toBeDisabled();
  await expect(title).toHaveValue('Retained unsaved revision');
  libraryMode = 'same';
  await refresh.click();
  await expect(save).toBeEnabled();
  await expect(selected).toHaveValue('1');
  await expect(title).toHaveValue('Retained unsaved revision');
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
