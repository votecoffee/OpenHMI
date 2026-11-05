import { test, expect } from '@playwright/test';

test.use({ actionTimeout: 8000 });

test('drag live tank, bar and radar controls onto a screen and handle bad data', async ({ page, context }) => {
  test.setTimeout(60000);
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const state = await (await page.request.get('/api/project')).json();
    const draft = await page.request.put('/api/project/draft', { data: { project, expected_revision: state.draft_revision } });
    expect(draft.ok(), await draft.text()).toBe(true);
    if (apply) {
      const result = await page.request.post('/api/project/apply', { data: { expected_revision: (await draft.json()).draft_revision } });
      expect(result.ok(), await result.text()).toBe(true);
    }
  }
  async function drop(name) {
    const block = page.getByRole('button', { name, exact: true });
    await block.scrollIntoViewIfNeeded();
    const source = await block.boundingBox();
    const target = await page.locator('.hmi-grid').boundingBox();
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
    await page.mouse.down();
    const x = target.x + target.width / 2;
    await page.mouse.move(x, target.y + 30, { steps: 12 });
    await page.mouse.move(x, target.y + 17, { steps: 3 });
    await page.mouse.up();
  }

  try {
    await save({ ...original.active, columns: 1, tags: [
      { name: 'ChartFlow', type: 'number', initial: -25 },
      { name: 'ChartPressure', type: 'number', initial: 50 },
    ] });
    await page.goto('/');
    for (const [name, kind] of [['Tank level indicator', 'tank'], ['Bar graph', 'bar'], ['Radar chart', 'radar']]) {
      await drop(name);
      await expect(page.locator(`[data-control="${kind}"]`)).toHaveCount(1);
      await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
    }
    await page.locator('[data-control="bar"] .hmi-label').click();
    await page.getByRole('spinbutton', { name: 'Scale minimum', exact: true }).fill('-100');
    const bars = page.getByRole('group', { name: 'Bar series', exact: true });
    await bars.getByRole('button', { name: 'Add bar', exact: true }).click();
    const second = bars.getByRole('group', { name: 'Bar 2', exact: true });
    await second.getByRole('combobox', { name: 'Tag', exact: true }).selectOption('ChartFlow');
    await second.getByLabel('Series label').fill('Return flow');
    await page.locator('[data-control="radar"] .hmi-label').click();
    const axes = page.getByRole('group', { name: 'Radar axes', exact: true });
    const third = axes.getByRole('group', { name: 'Axis 3', exact: true });
    await third.getByRole('combobox', { name: 'Tag', exact: true }).selectOption('ChartPressure');
    await third.getByLabel('Axis maximum').fill('200');
    await third.getByLabel('Units').fill('psi');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const controls = (await (await page.request.get('/api/project')).json()).active.controls;
    expect(controls.find(item => item.kind === 'radar').series[2]).toMatchObject({ tag: 'ChartPressure', maximum: 200, unit: 'psi' });

    let values = { TankLevel: 42, MotorRunning: true, ProcessAlarm: false, AlarmWord: 10, RecipeRevision: 1, ChartFlow: -25, ChartPressure: 50 };
    const viewer = await context.newPage();
    await viewer.route('**/api/tags', route => route.fulfill({ json: { driver: 'simulator', values } }));
    await viewer.goto('/runtime');
    const tank = viewer.locator('[data-control="tank"]');
    const bar = viewer.locator('[data-control="bar"] [data-chart-tag="ChartFlow"]');
    const radar = viewer.locator('[data-control="radar"]');
    await expect(tank.locator('[data-tank-fill]')).toHaveAttribute('style', 'height: 42%;');
    await expect(bar).toContainText('Return flow');
    await expect(bar).toContainText('-25.0');
    await expect(bar.locator('[data-bar-fill]')).toHaveAttribute('style', /left: 37.5%; width: 12.5%/);
    await expect(radar.locator('[data-radar-profile]')).toBeVisible();
    await expect(radar.locator('[data-chart-tag="ChartPressure"]')).toContainText('50.0 psi');
    if (process.env.OPENHMI_CHARTS_SCREENSHOT) await viewer.screenshot({ path: process.env.OPENHMI_CHARTS_SCREENSHOT, fullPage: true });

    values = { ...values, TankLevel: 120, ChartFlow: null, ChartPressure: null };
    await expect(tank).toContainText('120.0');
    await expect(tank).toContainText('OUT OF SCALE');
    await expect(tank.locator('[data-tank-fill]')).toHaveAttribute('style', 'height: 100%;');
    await expect(bar).toContainText('BAD DATA');
    await expect(bar.locator('[data-bar-fill]')).toHaveCount(0);
    await expect(radar.locator('[data-radar-profile]')).toHaveCount(0);
    await expect(radar.locator('[data-chart-tag="ChartPressure"]')).toContainText('BAD DATA');
    await expect(radar.locator('.radar-dot')).toHaveCount(2);
  } finally {
    await save(original.active);
    await save(original.draft, false);
  }
});
