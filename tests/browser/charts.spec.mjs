import { test, expect } from '@playwright/test';

test.use({ actionTimeout: 8000 });

test('drag live tank, gauge, bar, radar, pie and XY controls onto a screen and handle bad data', async ({ page, context }) => {
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
      { name: 'ChartParts', type: 'number', initial: 150 },
    ] });
    await page.goto('/');
    for (const [name, kind] of [['Tank level indicator', 'tank'], ['Radial gauge', 'gauge'], ['Bar graph', 'bar'], ['Radar chart', 'radar'], ['Pie chart', 'pie'], ['XY chart', 'xy']]) {
      await drop(name);
      await expect(page.locator(`[data-control="${kind}"]`)).toHaveCount(1);
      await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
    }
    await page.locator('[data-control="gauge"] .hmi-label').click();
    await page.getByRole('combobox', { name: 'Tag', exact: true }).selectOption({ label: 'ChartPressure' });
    await page.getByRole('spinbutton', { name: 'Scale minimum', exact: true }).fill('-50');
    await page.getByRole('spinbutton', { name: 'Scale maximum', exact: true }).fill('150');
    await page.getByRole('textbox', { name: 'Units', exact: true }).fill('psi');
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
    await page.locator('[data-control="pie"] .hmi-label').click();
    const slices = page.getByRole('group', { name: 'Pie slices', exact: true });
    const firstSlice = slices.getByRole('group', { name: 'Slice 1', exact: true });
    const secondSlice = slices.getByRole('group', { name: 'Slice 2', exact: true });
    await firstSlice.getByRole('combobox', { name: 'Tag', exact: true }).selectOption('ChartPressure');
    await secondSlice.getByRole('combobox', { name: 'Tag', exact: true }).selectOption('ChartParts');
    await expect(secondSlice.getByRole('combobox', { name: 'Tag', exact: true }).locator('option[value="ChartPressure"]')).toHaveCount(0);
    await firstSlice.getByLabel('Series label').fill('Accepted');
    await page.locator('[data-control="xy"] .hmi-label').click();
    await page.getByRole('spinbutton', { name: 'X minimum', exact: true }).fill('-50');
    await page.getByRole('spinbutton', { name: 'X maximum', exact: true }).fill('50');
    await page.getByRole('spinbutton', { name: 'Y maximum', exact: true }).fill('200');
    await page.getByRole('textbox', { name: 'X units', exact: true }).fill('gpm');
    await page.getByRole('textbox', { name: 'Y units', exact: true }).fill('psi');
    const xySeries = page.getByRole('group', { name: 'XY series', exact: true });
    const firstPoint = xySeries.getByRole('group', { name: 'Point 1', exact: true });
    await firstPoint.getByRole('combobox', { name: 'X tag', exact: true }).selectOption('ChartFlow');
    await firstPoint.getByRole('combobox', { name: 'Y tag', exact: true }).selectOption('ChartPressure');
    await firstPoint.getByLabel('Series label').fill('Return line');
    await xySeries.getByRole('button', { name: 'Add point', exact: true }).click();
    const secondPoint = xySeries.getByRole('group', { name: 'Point 2', exact: true });
    await secondPoint.getByRole('combobox', { name: 'X tag', exact: true }).selectOption('TankLevel');
    await secondPoint.getByRole('combobox', { name: 'Y tag', exact: true }).selectOption('AlarmWord');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const controls = (await (await page.request.get('/api/project')).json()).active.controls;
    expect(controls.find(item => item.kind === 'radar').series[2]).toMatchObject({ tag: 'ChartPressure', maximum: 200, unit: 'psi' });

    let values = { TankLevel: 42, MotorRunning: true, ProcessAlarm: false, AlarmWord: 10, RecipeRevision: 1, ChartFlow: -25, ChartPressure: 50, ChartParts: 150 };
    const viewer = await context.newPage();
    await viewer.route('**/api/tags', route => route.fulfill({ json: { driver: 'simulator', values } }));
    await viewer.goto('/runtime');
    const tank = viewer.locator('[data-control="tank"]');
    const gauge = viewer.locator('[data-control="gauge"]');
    const needle = gauge.locator('[data-gauge-needle] line');
    await expect(gauge).toContainText('50.0 psi');
    await expect(gauge).toContainText('Normal 20–80 psi');
    await expect(needle).toHaveAttribute('y2', '30');
    const bar = viewer.locator('[data-control="bar"] [data-chart-tag="ChartFlow"]');
    const radar = viewer.locator('[data-control="radar"]');
    await expect(tank.locator('[data-tank-fill]')).toHaveAttribute('style', 'height: 42%;');
    await expect(bar).toContainText('Return flow');
    await expect(bar).toContainText('-25.0');
    await expect(bar.locator('[data-bar-fill]')).toHaveAttribute('style', /left: 37.5%; width: 12.5%/);
    await expect(radar.locator('[data-radar-profile]')).toBeVisible();
    await expect(radar.locator('[data-chart-tag="ChartPressure"]')).toContainText('50.0 psi');
    const pie = viewer.locator('[data-control="pie"]');
    const plot = pie.getByRole('img', { name: 'Part totals proportions', exact: true });
    const accepted = pie.locator('[data-chart-tag="ChartPressure"]');
    await expect(plot.locator('[data-pie-slice]')).toHaveCount(2);
    await expect(accepted).toContainText('Accepted');
    await expect(accepted.locator('.pie-share')).toHaveText('25.0%');
    await expect(pie.locator('[data-chart-tag="ChartParts"] .pie-share')).toHaveText('75.0%');
    const xy = viewer.locator('[data-control="xy"]');
    const xyPoint = xy.locator('[data-xy-point="1"] circle');
    const returnLine = xy.locator('[data-xy-series="1"]');
    await expect(xyPoint).toHaveAttribute('cx', '50');
    await expect(xyPoint).toHaveAttribute('cy', '87');
    await expect(returnLine).toContainText('Return line');
    await expect(returnLine).toContainText('-25.0 gpm');
    await expect(returnLine).toContainText('50.0 psi');
    if (process.env.OPENHMI_CHARTS_SCREENSHOT) await viewer.screenshot({ path: process.env.OPENHMI_CHARTS_SCREENSHOT, fullPage: true });

    values = { ...values, ChartPressure: 90, ChartFlow: -80 };
    await expect(gauge).toContainText('OUTSIDE NORMAL BAND');
    await expect(returnLine).toContainText('OUT OF SCALE');
    await expect(returnLine).toContainText('-80.0 gpm');
    await expect(xyPoint).toHaveCount(0);
    await expect(xy.locator('[data-xy-point="2"]')).toBeVisible();
    values = { ...values, ChartPressure: 180 };
    await expect(gauge).toContainText('180.0 psi');
    await expect(gauge).toContainText('OUT OF SCALE');
    expect(Number(await needle.getAttribute('y2'))).toBeCloseTo(102);
    values = { ...values, TankLevel: 120, ChartFlow: null, ChartPressure: null };
    await expect(gauge).toContainText('BAD DATA');
    await expect(needle).toHaveCount(0);
    await expect(returnLine).toContainText('BAD DATA');
    await expect(xyPoint).toHaveCount(0);
    await expect(tank).toContainText('120.0');
    await expect(tank).toContainText('OUT OF SCALE');
    await expect(tank.locator('[data-tank-fill]')).toHaveAttribute('style', 'height: 100%;');
    await expect(bar).toContainText('BAD DATA');
    await expect(bar.locator('[data-bar-fill]')).toHaveCount(0);
    await expect(radar.locator('[data-radar-profile]')).toHaveCount(0);
    await expect(radar.locator('[data-chart-tag="ChartPressure"]')).toContainText('BAD DATA');
    await expect(radar.locator('.radar-dot')).toHaveCount(2);
    await expect(pie).toContainText('Pie unavailable');
    await expect(accepted).toContainText('BAD DATA');
    await expect(pie.locator('.pie-share')).toHaveCount(0);
    await expect(plot).toHaveCount(0);
    values = { ...values, ChartPressure: 1, ChartParts: -1 };
    await expect(pie).toContainText('Negative slice value');
    await expect(plot).toHaveCount(0);
    values = { ...values, ChartPressure: 0, ChartParts: 0 };
    await expect(pie).toContainText('All slice values are zero');
    await expect(plot).toHaveCount(0);
    values = { ...values, ChartParts: 150 };
    await expect(plot.locator('circle')).toHaveCount(1);
    await expect(accepted.locator('.pie-share')).toHaveText('0.0%');
  } finally {
    await save(original.active);
    await save(original.draft, false);
  }
});
