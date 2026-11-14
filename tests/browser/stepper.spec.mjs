import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8766', hasTouch: true });

test('numeric stepper previews bounded decimal edits and blocks stale entry', async ({ page }) => {
  test.setTimeout(60000);
  await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const current = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { project, expected_revision: current.draft_revision } });
    expect(saved.ok(), await saved.text()).toBe(true);
    if (apply) {
      const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } });
      expect(applied.ok(), await applied.text()).toBe(true);
    }
  }
  try {
    await save({ title: 'Stepper station', tags: [
      { name: 'Dose', type: 'number', writable: true, initial: 0.1 },
      { name: 'DoseHigh', type: 'number', initial: 0.35 },
    ], controls: [{ id: 'dose', kind: 'stepper', label: 'Dose', tag: 'Dose',
      minimum: 0, maximum: 1, maximum_tag: 'DoseHigh', step: 1, decimals: 2 }] });
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Numeric stepper', exact: true })).toBeVisible();
    await page.locator('[data-control="stepper"] .hmi-label').click();
    await page.getByRole('spinbutton', { name: 'Increment', exact: true }).fill('0.1');
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    expect((await (await page.request.get('/api/project')).json()).active.controls[0].step).toBe(0.1);
    await page.goto('/runtime');
    const control = page.locator('[data-control="stepper"]');
    const increase = control.getByRole('button', { name: 'Increase Dose', exact: true });
    const decrease = control.getByRole('button', { name: 'Decrease Dose', exact: true });
    const write = control.getByRole('button', { name: 'Write value', exact: true });
    await expect(write).toBeDisabled();
    await increase.tap();
    await increase.tap();
    await expect(control.locator('output')).toHaveText('Proposed value: 0.3');
    await expect(increase).toBeDisabled();
    expect((await (await page.request.get('/api/tags')).json()).values.Dose).toBe(0.1);
    await control.getByRole('button', { name: 'Reset proposed value', exact: true }).tap();
    await expect(write).toBeDisabled();
    await increase.tap();
    await increase.tap();
    await decrease.tap();
    await write.tap();
    await expect(control.locator('.hmi-value')).toContainText('0.20');
    await expect(write).toBeDisabled();
    await increase.tap();
    const changed = (await (await page.request.get('/api/project')).json()).active;
    changed.controls[0].label = 'Dose updated';
    await save(changed);
    await expect(control).toContainText('Dose updated');
    await expect(write).toBeDisabled();
    await expect(control.locator('output')).toHaveCount(0);
    await control.getByRole('button', { name: 'Increase Dose updated', exact: true }).tap();
    await expect(control.locator('output')).toHaveText('Proposed value: 0.3');
    const data = await (await page.request.get('/api/tags')).json();
    data.samples.DoseHigh = { quality: 'stale', age_seconds: 4 };
    await page.route('**/api/tags', route => route.fulfill({ json: data }));
    await expect(control).toContainText('STALE DATA');
    await expect(write).toBeDisabled();
    await expect(control.getByRole('button', { name: 'Increase Dose updated', exact: true })).toBeDisabled();
    await page.unroute('**/api/tags');
    await expect(write).toBeEnabled();
    await page.request.post('/api/security/logout');
    await expect(write).toBeDisabled();
    expect((await (await page.request.get('/api/tags')).json()).values.Dose).toBe(0.2);
  } finally {
    await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
    await save(original.active);
    if (JSON.stringify(original.draft) !== JSON.stringify(original.active)) await save(original.draft, false);
  }
});
