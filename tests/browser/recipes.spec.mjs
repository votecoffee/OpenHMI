import { test, expect } from '@playwright/test';
import { fulfillProjectRead } from './project-reply.mjs';
import { fileURLToPath } from 'node:url';

test('malformed recipe identity replies retain confirmed identity and recover by refresh', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/recipe-editor');
  const session = page.locator('.recipe-session');
  let logins = 0, logouts = 0;
  await page.route('**/api/recipe-auth/login', async route => {
    logins += 1;
    const response = await route.fetch();
    const body = await response.json();
    await fulfillProjectRead(route, { response, json: { ...body, user: { ...body.user, roles: {} } } });
  });
  await session.getByLabel('Recipe user', { exact: true }).fill('engineer');
  await session.getByLabel('Password', { exact: true }).fill('RecipeTestOnly-2026!');
  await session.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(session.getByRole('alert')).toContainText('Invalid recipe sign-in response');
  await expect(session.getByRole('button', { name: 'Sign out', exact: true })).toHaveCount(0);
  await page.unroute('**/api/recipe-auth/login');
  await page.getByRole('button', { name: 'Refresh recipes', exact: true }).click();
  await expect(session).toContainText('Signed in: engineer');
  await expect(session.getByRole('alert')).toHaveCount(0);
  await page.route('**/api/recipe-auth/session', route => fulfillProjectRead(route, { json: { configured: true, user: { name: 'Malformed', roles: {} } } }));
  await page.getByRole('button', { name: 'Refresh recipes', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Invalid recipe session response');
  await expect(session).toContainText('Signed in: engineer');
  await expect(page.getByRole('button', { name: 'Create recipe', exact: true })).toBeDisabled();
  await page.unroute('**/api/recipe-auth/session');
  await page.getByRole('button', { name: 'Refresh recipes', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.route('**/api/recipe-auth/logout', async route => {
    logouts += 1;
    const response = await route.fetch();
    await fulfillProjectRead(route, { response, json: { ok: false } });
  });
  await session.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(session.getByRole('alert')).toContainText('Invalid recipe sign-out response');
  await expect(session).toContainText('Signed in: engineer');
  await page.unroute('**/api/recipe-auth/logout');
  await page.getByRole('button', { name: 'Refresh recipes', exact: true }).click();
  await expect(session.getByLabel('Password', { exact: true })).toHaveValue('');
  await expect(session.getByRole('alert')).toHaveCount(0);
  expect(logins).toBe(1); expect(logouts).toBe(1);
  expect(errors).toEqual([]);
});

test('recipe library faults retain unsaved edits and recover without writing', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const library = await (await page.request.get('/api/recipes')).json();
  let reply = { json: { revisions: null } }, writes = 0;
  await page.route('**/api/recipes', route => {
    if (route.request().method() !== 'GET') { writes += 1; return route.continue(); }
    return reply ? fulfillProjectRead(route, reply) : route.continue();
  });
  await page.goto('/recipe-editor');
  await expect(page.getByRole('alert')).toContainText('Invalid recipe library response');
  reply = null;
  await page.getByRole('button', { name: 'Retry recipe library', exact: true }).click();
  await page.getByLabel('Recipe user', { exact: true }).fill('engineer');
  await page.getByLabel('Password', { exact: true }).fill('RecipeTestOnly-2026!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Recipe code', { exact: true }).fill('UNSAVED');
  const title = page.getByLabel('Recipe title', { exact: true });
  await title.fill('Unsaved library fixture');
  reply = { json: { ...library, change_policy: { version: 1, policy: null } } };
  await page.getByRole('button', { name: 'Refresh recipes', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Showing the last readable library');
  await expect(title).toHaveValue('Unsaved library fixture');
  await expect(page.getByRole('button', { name: 'Create recipe', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Clear loaded copy', exact: true })).toBeDisabled();
  await expect(page.locator('.recipe-session')).toContainText('Signed in: engineer');
  reply = { status: 503, json: { detail: 'Synthetic library outage' } };
  await page.getByRole('button', { name: 'Refresh recipes', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic library outage');
  reply = null;
  await page.getByRole('button', { name: 'Refresh recipes', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(title).toHaveValue('Unsaved library fixture');
  await expect(page.getByRole('button', { name: 'Create recipe', exact: true })).toBeEnabled();
  expect(writes).toBe(0);
  expect(errors).toEqual([]);
});

test('recipe-local session preserves sign-in when logout fails', async ({ page }) => {
  await page.goto('/recipe-editor');
  const session = page.locator('.recipe-session');
  await session.getByLabel('Recipe user', { exact: true }).fill('engineer');
  await session.getByLabel('Password', { exact: true }).fill('Incorrect fixture password');
  await session.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(session.getByRole('alert')).toContainText('Invalid recipe credentials');
  await session.getByLabel('Password', { exact: true }).fill('RecipeTestOnly-2026!');
  await session.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(session).toContainText('Signed in: engineer');
  await expect(session.getByRole('alert')).toHaveCount(0);
  const endpoint = '**/api/recipe-auth/logout';
  await page.route(endpoint, route => fulfillProjectRead(route, { status: 503, json: { detail: 'Synthetic logout outage' } }));
  await session.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(session.getByRole('alert')).toContainText('Synthetic logout outage');
  await expect(session).toContainText('Signed in: engineer');
  await page.unroute(endpoint);
  await session.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(session.getByLabel('Password', { exact: true })).toHaveValue('');
  expect((await (await page.request.get('/api/recipe-auth/session')).json()).user).toBeNull();
});

test('recipe workspace delegates sign-in and permissions to HMI security', async ({ page }) => {
  await page.goto('http://127.0.0.1:8766/recipe-editor');
  const create = page.getByRole('button', { name: 'Create recipe', exact: true });
  await expect(page.getByText('Recipe permissions use the signed-in HMI account.', { exact: true })).toBeVisible();
  await expect(page.locator('.recipe-session')).toHaveCount(0);
  await expect(create).toBeDisabled();
  await page.getByRole('button', { name: 'Open HMI login', exact: true }).first().click();
  await page.getByLabel('HMI user', { exact: true }).fill('admin');
  await page.getByLabel('HMI password', { exact: true }).fill('SecurityTestOnly-2026!');
  await page.getByRole('button', { name: 'Sign in to HMI', exact: true }).click();
  await expect(create).toBeEnabled();
  await expect(page.locator('.recipe-session')).toHaveCount(0);
  await page.getByRole('button', { name: 'Sign out of HMI', exact: true }).click();
  await expect(create).toBeDisabled();
  await expect(page.locator('.recipe-session')).toHaveCount(0);
});

test('recipe policy reports stale updates and recovers after refresh', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('/recipe-editor');
  await page.getByLabel('Recipe user', { exact: true }).fill('manager');
  await page.getByLabel('Password', { exact: true }).fill('RecipeTestOnly-2026!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click({ timeout: 5000 });
  const original = (await (await page.request.get('/api/recipes')).json()).change_policy.policy;
  const policy = page.locator('.recipe-policy');
  const reason = page.locator('.recipe-reason textarea');
  const status = page.getByRole('status', { name: 'Recipe operation' });
  try {
    await policy.locator('summary').click({ timeout: 5000 });
    await policy.getByLabel('editing enabled', { exact: true }).uncheck({ timeout: 5000 });
    await reason.fill('Offline editing freeze');
    await policy.getByRole('button', { name: 'Save change policy', exact: true }).click({ timeout: 5000 });
    await expect(page.locator('.recipe-gates')).toContainText('editing: blocked');
    await expect(policy).toContainText('Offline editing freeze');
    const current = (await (await page.request.get('/api/recipes')).json()).change_policy;
    expect((await page.request.put('/api/recipes/policy', { data: {
      policy: original, expected_version: current.version, reason: 'Concurrent fixture editor' },
    })).ok()).toBe(true);
    await policy.getByLabel('editing enabled', { exact: true }).check({ timeout: 5000 });
    await reason.fill('Stale fixture save');
    await policy.getByRole('button', { name: 'Save change policy', exact: true }).click({ timeout: 5000 });
    await expect(status).toContainText('Recipe policy changed; reload before updating');
    await page.getByRole('button', { name: 'Refresh recipes', exact: true }).click({ timeout: 5000 });
    await expect(page.locator('.recipe-gates')).toContainText('editing: allowed');
    await policy.getByLabel('loading enabled', { exact: true }).uncheck({ timeout: 5000 });
    await expect(reason).toHaveAccessibleName('Change / approval / load reason');
    await reason.fill('Refreshed fixture save', { timeout: 5000 });
    await policy.getByRole('button', { name: 'Save change policy', exact: true }).click({ timeout: 5000 });
    await expect(page.locator('.recipe-gates')).toContainText('loading: blocked');
  } finally {
    const current = (await (await page.request.get('/api/recipes', { timeout: 5000 })).json()).change_policy;
    expect((await page.request.put('/api/recipes/policy', { data: {
      policy: original, expected_version: current.version, reason: 'Restore offline fixture policy' }, timeout: 5000,
    })).ok()).toBe(true);
  }
});

test('recipe image, same-user approval and independent production copy', async ({ page, context }) => {
  test.setTimeout(60000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/recipe-editor');
  await page.getByLabel('Recipe user', { exact: true }).fill('engineer');
  await page.getByLabel('Password', { exact: true }).fill('RecipeTestOnly-2026!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Recipe code', { exact: true }).fill('REC-A');
  await page.getByLabel('Recipe title', { exact: true }).fill('Fixture A');
  await page.getByLabel('Description', { exact: true }).fill('Synthetic fixture recipe for browser validation');
  await page.getByLabel('Change / approval / load reason', { exact: true }).fill('Initial trial setup');
  await page.getByLabel('Recipe image (PNG/JPEG)', { exact: true }).setInputFiles(fileURLToPath(new URL('../fixtures/recipe-part.png', import.meta.url)));
  await expect(page.getByRole('status', { name: 'Recipe operation' })).toContainText('Image uploaded');
  await page.getByRole('button', { name: 'Add parameter', exact: true }).click();
  await page.getByLabel('Parameter 1 name', { exact: true }).fill('speed');
  await page.getByLabel('Parameter 1 label', { exact: true }).fill('Conveyor speed');
  await page.getByLabel('Parameter 1 value', { exact: true }).fill('45.5');
  await page.getByLabel('Parameter 1 units', { exact: true }).fill('rpm');
  await page.getByLabel('Parameter 1 minimum', { exact: true }).fill('0');
  await page.getByLabel('Parameter 1 maximum', { exact: true }).fill('100');
  for (const [index, name, label, type, value] of [
    [2, 'enabled', 'Enabled fixture', 'boolean', true],
    [3, 'batch', 'Batch fixture', 'text', '001, 设备 Δ'],
    [4, 'count', 'Count fixture', 'integer', '7'],
  ]) {
    await page.getByRole('button', { name: 'Add parameter', exact: true }).click();
    await page.getByLabel(`Parameter ${index} name`, { exact: true }).fill(name);
    await page.getByLabel(`Parameter ${index} label`, { exact: true }).fill(label);
    await page.getByLabel(`Parameter ${index} type`, { exact: true }).selectOption(type);
    const entry = page.getByLabel(`Parameter ${index} value`, { exact: true });
    if (type === 'boolean') await entry.check(); else await entry.fill(value);
    if (type === 'boolean' || type === 'text') await expect(page.getByLabel(`Parameter ${index} minimum`, { exact: true })).toBeDisabled();
  }
  await page.getByRole('button', { name: 'Add parameter', exact: true }).click();
  await page.getByRole('button', { name: 'Remove 5', exact: true }).click();
  await expect(page.locator('[data-parameter-row]')).toHaveCount(4);
  await page.getByRole('button', { name: 'Create recipe', exact: true }).click();
  await expect(page.locator('.recipe-review-state')).toContainText('draft');
  const viewer = await context.newPage();
  viewer.on('pageerror', error => errors.push(error.message));
  await viewer.goto('/recipes');
  await expect(viewer.locator('.recipe-preview .recipe-image')).toBeVisible();
  await expect(viewer.locator('.recipe-loaded')).toContainText('No recipe loaded');
  await viewer.getByLabel('Change / approval / load reason', { exact: true }).fill('Trial load before production approval');
  await viewer.getByRole('button', { name: 'Load recipe', exact: true }).click();
  await expect(viewer.locator('.recipe-loaded')).toContainText('NOT PRODUCTION APPROVED');
  await expect(viewer.locator('.recipe-loaded')).toContainText('45.5');
  await expect(viewer.locator('.recipe-loaded .recipe-values')).toContainText('001, 设备 Δ');
  await expect(viewer.locator('.recipe-loaded .recipe-values tr').filter({ hasText: 'Enabled fixture' }).getByRole('cell', { name: 'ON', exact: true })).toBeVisible();
  const typed = (await (await viewer.request.get('/api/recipes/selected')).json()).snapshot.content.parameters;
  expect(typed.map(parameter => [parameter.type, parameter.value])).toEqual([
    ['number', 45.5], ['boolean', true], ['text', '001, 设备 Δ'], ['integer', 7],
  ]);
  await page.getByLabel('Change / approval / load reason', { exact: true }).fill('Trial complete; ready for review');
  await page.getByRole('button', { name: 'Submit for approval', exact: true }).click();
  await expect(page.locator('.recipe-review-state')).toContainText('in_review');
  await page.getByLabel('Change / approval / load reason', { exact: true }).fill('Approved after trial inspection');
  await page.getByRole('button', { name: 'Approve for production', exact: true }).click();
  await expect(page.locator('.recipe-review-state')).toContainText('Approved by: engineer');
  await expect(viewer.locator('.recipe-loaded')).toContainText('NOT PRODUCTION APPROVED');
  await viewer.getByRole('button', { name: 'Refresh recipes', exact: true }).click();
  await expect(viewer.locator('.recipe-review-state')).toContainText('approved');
  await viewer.getByLabel('Change / approval / load reason', { exact: true }).fill('Load approved production copy');
  await viewer.getByRole('button', { name: 'Load recipe', exact: true }).click();
  await expect(viewer.locator('.recipe-loaded .recipe-production')).toHaveText('PRODUCTION APPROVED');
  await expect(viewer.locator('.recipe-loaded .recipe-image')).toBeVisible();
  const selected = await (await viewer.request.get('/api/recipes/selected')).json();
  const loaded = viewer.locator('.recipe-loaded');
  const load = viewer.getByRole('button', { name: 'Load recipe', exact: true });
  const clear = viewer.getByRole('button', { name: 'Clear loaded copy', exact: true });
  const endpoint = '**/api/recipes/selected';
  let selection = selected;
  await viewer.route(endpoint, route => fulfillProjectRead(route, { body: JSON.stringify(selection), contentType: 'application/json' }));
  for (const invalid of [{}, { ...selected, version: '2' }, { ...selected, snapshot: {} },
    { ...selected, snapshot: { ...selected.snapshot, production_approved: 'false' } },
    { ...selected, snapshot: { ...selected.snapshot, content: { ...selected.snapshot.content, parameters: [null] } } }]) {
    selection = invalid;
    await expect(loaded).toContainText('Recipe selection unavailable');
    await expect(loaded).not.toContainText('PRODUCTION APPROVED');
    await expect(load).toBeDisabled();
    await expect(clear).toBeDisabled();
    selection = selected;
    await expect(loaded.locator('.recipe-production')).toHaveText('PRODUCTION APPROVED');
    await expect(load).toBeEnabled();
    await expect(clear).toBeEnabled();
  }
  await viewer.unroute(endpoint);
  if (process.env.OPENHMI_RECIPE_VIEWER) await viewer.screenshot({ path: process.env.OPENHMI_RECIPE_VIEWER, fullPage: true });
  await page.getByLabel('Parameter 1 value', { exact: true }).fill('60');
  await page.getByLabel('Change / approval / load reason', { exact: true }).fill('Next trial speed');
  await page.getByRole('button', { name: 'Save new revision', exact: true }).click();
  await expect(page.locator('.recipe-review-state')).toContainText('r2');
  await expect(page.locator('.recipe-review-state')).toContainText('draft');
  await expect(page.locator('.recipe-loaded')).toContainText('45.5');
  await expect(page.locator('.recipe-loaded .recipe-production')).toHaveText('PRODUCTION APPROVED');
  await expect(page.locator('.recipe-history')).toContainText('parameters.speed.value');
  if (process.env.OPENHMI_RECIPE_EDITOR) await page.screenshot({ path: process.env.OPENHMI_RECIPE_EDITOR, fullPage: true });
  const projectState = await (await page.request.get('/api/project')).json();
  projectState.draft.controls.push({ id: 'loaded_product', kind: 'recipe', label: 'Selected product' });
  const saved = await page.request.put('/api/project/draft', { data: { expected_revision: projectState.draft_revision, project: projectState.draft } });
  expect(saved.ok()).toBe(true);
  expect((await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } })).ok()).toBe(true);
  await viewer.goto('/runtime');
  await expect(viewer.locator('[data-control="recipe"]')).toContainText('Fixture A');
  await expect(viewer.locator('[data-control="recipe"] .recipe-image')).toBeVisible();
  const compact = viewer.locator('[data-control="recipe"]');
  selection = null;
  await viewer.route(endpoint, route => fulfillProjectRead(route, { body: JSON.stringify(selection), contentType: 'application/json' }));
  await expect(compact).toContainText('Recipe selection unavailable');
  await expect(compact).not.toContainText('Fixture A');
  selection = selected;
  await expect(compact).toContainText('Fixture A');
  await viewer.unroute(endpoint);
  expect((await (await page.request.get('/api/tags')).json()).values.RecipeProductionApproved).toBe(true);
  expect(errors).toEqual([]);
});
