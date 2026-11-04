import { test, expect } from '@playwright/test';

test.use({ actionTimeout: 15000 });

async function save(page, project, apply = true) {
  const state = await (await page.request.get('/api/project')).json();
  const response = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
  expect(response.ok(), await response.text()).toBe(true);
  if (apply) {
    const result = await page.request.post('/api/project/apply', { data: { expected_revision: (await response.json()).draft_revision, reason: 'Browser revision fixture' } });
    expect(result.ok(), await result.text()).toBe(true);
  }
}

test('compare history, stage screen-only rollback and apply a new revision', async ({ page }) => {
  test.setTimeout(90000);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const original = await (await page.request.get('/api/project')).json();
  const beforeMotor = (await (await page.request.get('/api/tags')).json()).values.MotorRunning;
  const target = original.active_revision;
  const numeric = original.active.controls.find(item => item.kind === 'numeric');
  try {
    const changed = structuredClone(original.active);
    changed.controls.find(item => item.id === numeric.id).label = 'Revision trial level';
    changed.tags.push({ name: 'RetainedSetpoint', type: 'integer', initial: 7, writable: true });
    await save(page, changed);
    const activeBefore = (await (await page.request.get('/api/project')).json()).active_revision;
    await page.goto('/revisions');
    await expect(page.getByRole('region', { name: 'Project revisions', exact: true })).toBeVisible();
    await page.getByRole('button', { name: `Compare revision ${target}`, exact: true }).click();
    const comparison = page.getByRole('region', { name: 'Revision comparison', exact: true });
    await expect(comparison).toContainText('Revision trial level');
    await expect(page.getByLabel('Restore scope', { exact: true })).toHaveValue('screens');
    if (process.env.OPENHMI_PROJECT_HISTORY_SCREENSHOT) await comparison.screenshot({ path: process.env.OPENHMI_PROJECT_HISTORY_SCREENSHOT });
    await page.getByLabel('Restore reason', { exact: true }).fill('Reviewed screen-only rollback');
    await page.getByRole('button', { name: 'Stage revision as draft', exact: true }).click();
    await expect(page.getByRole('status')).toContainText('Staged draft');
    let state = await (await page.request.get('/api/project')).json();
    expect(state.active_revision).toBe(activeBefore);
    expect(state.active.controls.find(item => item.id === numeric.id).label).toBe('Revision trial level');
    expect(state.draft.tags.some(item => item.name === 'RetainedSetpoint')).toBe(true);
    await page.getByRole('link', { name: 'Open staged draft in editor', exact: true }).click();
    await expect(page.locator('[data-control="numeric"]').first()).toContainText(numeric.label);
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    state = await (await page.request.get('/api/project')).json();
    expect(state.active_revision).toBe(activeBefore + 1);
    expect(state.active.tags.some(item => item.name === 'RetainedSetpoint')).toBe(true);
    const revision = await (await page.request.get(`/api/project/revisions/${state.active_revision}`)).json();
    expect(revision.source_revision).toBe(target);
    expect(revision.reason).toBe('Reviewed screen-only rollback');
    expect((await (await page.request.get('/api/tags')).json()).values.MotorRunning).toBe(beforeMotor);
    expect(errors).toEqual([]);
  } finally { await save(page, original.active); await save(page, original.draft, false); }
});

test('stale editor survives reload, merges explicit conflicts and imports a recovery export', async ({ page, context }, testInfo) => {
  test.setTimeout(120000);
  const original = await (await page.request.get('/api/project')).json();
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const other = await context.newPage(); other.on('pageerror', error => errors.push(error.message));
  try {
    await Promise.all([page.goto('/'), other.goto('/')]);
    const numeric = original.draft.controls.find(item => item.kind === 'numeric');
    const indicator = original.draft.controls.find(item => item.kind === 'indicator');
    await page.route('**/api/security/session', route => route.abort());
    await expect(page.getByText('HMI identity status unavailable. Showing the last confirmed sign-in; the server checks permission on every operation.', { exact: true })).toBeVisible();
    await page.locator('[data-control="numeric"]').first().click();
    await page.getByRole('textbox', { name: 'Label', exact: true }).fill('First writer level');
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
    await page.unroute('**/api/security/session');
    await other.locator('[data-control="numeric"]').first().click();
    await other.getByRole('textbox', { name: 'Label', exact: true }).fill('Retained local level');
    await expect(other.getByRole('dialog', { name: 'Recover editor changes', exact: true })).toBeVisible();
    await expect(other.getByRole('button', { name: 'Save reviewed merged draft', exact: true })).toBeDisabled();
    // The other tab can keep saving without erasing this tab's recovery cache.
    await page.locator('[data-control="indicator"]').first().click();
    await page.getByRole('textbox', { name: 'Label', exact: true }).fill('Independent motor label');
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
    await other.reload();
    const dialog = other.getByRole('dialog', { name: 'Recover editor changes', exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('Retained local level');
    await other.getByLabel(`Use local /controls/@${numeric.id}/label`, { exact: true }).check();
    await expect(other.getByRole('button', { name: 'Save reviewed merged draft', exact: true })).toBeEnabled();
    const downloadPromise = other.waitForEvent('download');
    await dialog.getByRole('button', { name: 'Export local recovery JSON', exact: true }).click();
    const file = testInfo.outputPath('recovery.json'); await (await downloadPromise).saveAs(file);
    if (process.env.OPENHMI_PROJECT_MERGE_SCREENSHOT) await dialog.screenshot({ path: process.env.OPENHMI_PROJECT_MERGE_SCREENSHOT });
    await other.getByRole('button', { name: 'Save reviewed merged draft', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(other.getByRole('status', { name: 'Draft status' })).toContainText('Merged draft');
    let state = await (await other.request.get('/api/project')).json();
    expect(state.draft.controls.find(item => item.id === numeric.id).label).toBe('Retained local level');
    expect(state.draft.controls.find(item => item.id === indicator.id).label).toBe('Independent motor label');
    expect(state.active_revision).toBe(original.active_revision);
    await other.goto('/revisions');
    await other.getByLabel('Import local recovery JSON', { exact: true }).setInputFiles(file);
    await expect(other.getByRole('dialog', { name: 'Recover editor changes', exact: true })).toBeVisible();
    await expect(other.getByRole('button', { name: 'Save reviewed merged draft', exact: true })).toBeEnabled();
    await other.getByRole('button', { name: 'Save reviewed merged draft', exact: true }).click();
    await expect(other.getByRole('dialog', { name: 'Recover editor changes', exact: true })).toHaveCount(0);
    const copies = await (await other.request.get('/api/project/recoveries')).json();
    expect(copies.items.length).toBeGreaterThanOrEqual(4);
    expect(errors).toEqual([]);
  } finally { await other.close(); await save(page, original.active); await save(page, original.draft, false); }
});
