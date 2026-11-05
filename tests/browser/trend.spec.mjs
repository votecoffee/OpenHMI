import { test, expect } from '@playwright/test';

test('configure independent trend scales, live precision, and aligned Boolean lanes', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const state = await (await page.request.get('/api/project')).json();
    const result = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
    expect(result.ok(), await result.text()).toBe(true);
    if (apply) {
      const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await result.json()).draft_revision } });
      expect(applied.ok(), await applied.text()).toBe(true);
    }
  }

  try {
    const project = structuredClone(original.active);
    project.columns = 1;
    project.tags.push({ name: 'Pressure', type: 'number', initial: 1050.25 });
    project.controls.push({ id: 'trend', kind: 'trend', label: 'Process trend', tags: ['TankLevel'], seconds: 60 });
    await save(project);
    await page.goto('/');
    await page.locator('[data-control="trend"] .hmi-label').click();
    const fields = page.getByRole('group', { name: 'Trend tags', exact: true });
    await fields.getByLabel('Add trend tag').selectOption('Pressure');
    await fields.getByLabel('Add trend tag').selectOption('MotorRunning');
    await fields.getByLabel('Add trend tag').selectOption('ProcessAlarm');
    await fields.getByLabel('TankLevel decimal places').selectOption('3');
    await fields.getByLabel('Pressure decimal places').selectOption('2');
    await fields.getByLabel('TankLevel Y-axis range').selectOption('fixed');
    await fields.getByLabel('TankLevel minimum').fill('20');
    await fields.getByLabel('TankLevel maximum').fill('10');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Fixed trend scale requires');
    await fields.getByLabel('TankLevel maximum').fill('60');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');

    // Deterministic samples exercise scale and step geometry independently of acquisition timing.
    await page.route(url => url.pathname === '/api/history', route => {
      const query = new URL(route.request().url()).searchParams;
      const seconds = Number(query.get('seconds'));
      const end = Number(query.get('end') ?? 1800000000);
      const start = end - seconds;
      const sample = (tag, position, value, quality = 'good') => ({ tag, epoch: start + position * seconds, value, quality });
      return route.fulfill({ json: { start, end, truncated: false, samples: [
        sample('TankLevel', 0, 30), sample('TankLevel', 0.25, 50), sample('TankLevel', 0.5, null, 'bad'), sample('TankLevel', 0.75, 50),
        sample('Pressure', 0, 1000), sample('Pressure', 0.25, 1200),
        sample('MotorRunning', 0, false), sample('MotorRunning', 0.25, true),
        sample('ProcessAlarm', 0, true), sample('ProcessAlarm', 0.25, false),
      ] } });
    });
    await page.goto('/runtime');
    const chart = page.locator('[data-control="trend"]');
    const tank = chart.locator('[data-trend-tag="TankLevel"]');
    await expect(tank.locator('polyline')).toHaveAttribute('points', '0,120 150,40');
    await expect(tank.locator('circle')).toHaveCount(1);
    await expect(chart.locator('[data-trend-tag="Pressure"] polyline')).toHaveAttribute('points', '0,160 150,0');
    await expect(chart.locator('[data-trend-lane="MotorRunning"] polyline')).toHaveAttribute('points', '0,23 150,23 150,5');
    await expect(chart.locator('[data-trend-lane="ProcessAlarm"] polyline')).toHaveAttribute('points', '0,5 150,5 150,23');
    await expect(chart.locator('[data-trend-value="TankLevel"]')).toContainText('42.000');
    await expect(chart.locator('[data-trend-value="TankLevel"]')).toContainText('20 to 60 Fixed');
    await expect(chart.locator('[data-trend-value="Pressure"]')).toContainText('1050.25');
    await expect(chart.locator('[data-trend-value="Pressure"]')).toContainText('1000 to 1200 Observed');
    await expect(chart.locator('[data-trend-value="MotorRunning"]')).toContainText('ON');
    await page.getByLabel('Process trend history end').fill('2026-01-01T08:00');
    await expect(chart.getByRole('link', { name: 'Export history CSV' })).toHaveAttribute('href', /&end=\d+/);
    await expect(chart.locator('[data-trend-value="TankLevel"]')).toContainText('42.000');
    await chart.getByRole('button', { name: 'Live', exact: true }).click();
    await expect(chart.getByRole('link', { name: 'Export history CSV' })).not.toHaveAttribute('href', /&end=/);
    if (process.env.OPENHMI_TREND_SCREENSHOT) await chart.screenshot({ path: process.env.OPENHMI_TREND_SCREENSHOT });
  } finally {
    await save(original.active);
    await save(original.draft, false);
  }
});
