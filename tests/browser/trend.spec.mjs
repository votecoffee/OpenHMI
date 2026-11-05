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
    project.tags.push(
      { name: 'TrendLevel', type: 'number', initial: 42 },
      { name: 'TrendPressure', type: 'number', initial: 1050.25 },
      { name: 'TrendMotor', type: 'boolean', initial: true },
      { name: 'TrendAlarm', type: 'boolean', initial: false },
    );
    project.controls.push({ id: 'trend', kind: 'trend', label: 'Process trend', tags: ['TrendLevel'], seconds: 60 });
    await save(project);
    await page.goto('/');
    await page.locator('[data-control="trend"] .hmi-label').click();
    const fields = page.getByRole('group', { name: 'Trend tags', exact: true });
    await fields.getByLabel('Add trend tag').selectOption('TrendPressure');
    await fields.getByLabel('Add trend tag').selectOption('TrendMotor');
    await fields.getByLabel('Add trend tag').selectOption('TrendAlarm');
    await fields.getByLabel('TrendLevel decimal places').selectOption('3');
    await fields.getByLabel('TrendPressure decimal places').selectOption('2');
    await fields.getByLabel('TrendLevel Y-axis range').selectOption('fixed');
    await fields.getByLabel('TrendLevel minimum').fill('20');
    await fields.getByLabel('TrendLevel maximum').fill('10');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Fixed trend scale requires');
    await fields.getByLabel('TrendLevel maximum').fill('60');
    const recording = page.getByRole('group', { name: 'Saved trend recording', exact: true });
    await recording.getByLabel('Enable recording').check();
    await recording.getByLabel('Record interval (ms)').fill('100');
    await recording.getByLabel('Retained samples per capture').fill('10');
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
        sample('TrendLevel', 0, 30), sample('TrendLevel', 0.25, 50), sample('TrendLevel', 0.5, null, 'bad'), sample('TrendLevel', 0.75, 50),
        sample('TrendPressure', 0, 1000), sample('TrendPressure', 0.25, 1200),
        sample('TrendMotor', 0, false), sample('TrendMotor', 0.25, true),
        sample('TrendAlarm', 0, true), sample('TrendAlarm', 0.25, false),
      ] } });
    });
    await page.goto('/runtime');
    const chart = page.locator('[data-control="trend"]');
    const tank = chart.locator('[data-trend-tag="TrendLevel"]');
    await expect(tank.locator('polyline')).toHaveAttribute('points', '0,120 150,40');
    await expect(tank.locator('circle')).toHaveCount(1);
    await expect(chart.locator('[data-trend-tag="TrendPressure"] polyline')).toHaveAttribute('points', '0,160 150,0');
    await expect(chart.locator('[data-trend-lane="TrendMotor"] polyline')).toHaveAttribute('points', '0,23 150,23 150,5');
    await expect(chart.locator('[data-trend-lane="TrendAlarm"] polyline')).toHaveAttribute('points', '0,5 150,5 150,23');
    await expect(chart.locator('[data-trend-value="TrendLevel"]')).toContainText('42.000');
    await expect(chart.locator('[data-trend-value="TrendLevel"]')).toContainText('20 to 60 Fixed');
    await expect(chart.locator('[data-trend-value="TrendPressure"]')).toContainText('1050.25');
    await expect(chart.locator('[data-trend-value="TrendPressure"]')).toContainText('1000 to 1200 Observed');
    await expect(chart.locator('[data-trend-value="TrendMotor"]')).toContainText('ON');
    await page.getByLabel('Process trend history end').fill('2026-01-01T08:00');
    await expect(chart.getByRole('link', { name: 'Export history CSV' })).toHaveAttribute('href', /&end=\d+/);
    await expect(chart.locator('[data-trend-value="TrendLevel"]')).toContainText('42.000');
    await chart.getByRole('button', { name: 'Live', exact: true }).click();
    await expect(chart.getByRole('link', { name: 'Export history CSV' })).not.toHaveAttribute('href', /&end=/);
    await page.getByLabel('Process trend time range').selectOption('10');
    await expect(chart.getByRole('link', { name: 'Export history CSV' })).toHaveAttribute('href', /seconds=10/);
    const customWindow = page.getByLabel('Process trend window seconds');
    await customWindow.fill('17');
    await customWindow.press('Enter');
    await expect(chart.getByRole('link', { name: 'Export history CSV' })).toHaveAttribute('href', /seconds=17/);
    const analog = chart.getByRole('img', { name: 'Process trend trend', exact: true });
    const point = await analog.boundingBox();
    await analog.hover({ position: { x: point.width / 8, y: point.height / 2 } });
    await expect(chart.locator('[data-trend-cursor]')).toHaveCount(3);
    const atLevel = chart.locator('[data-trend-value="TrendLevel"] [data-trend-cursor-value]');
    await expect.poll(async () => Math.abs(Number(await atLevel.textContent()) - 40)).toBeLessThan(0.5);
    await expect(chart.locator('[data-trend-value="TrendMotor"] [data-trend-cursor-value]')).toHaveText('OFF');
    await analog.hover({ position: { x: point.width * 0.6, y: point.height / 2 } });
    await expect(chart.locator('[data-trend-value="TrendLevel"] [data-trend-cursor-value]')).toHaveText(/^.$/u);

    await chart.getByRole('button', { name: 'Run trend' }).click();
    await expect(chart.getByText(/10 \/ 10 samples retained.*rolled off/)).toBeVisible();
    await chart.getByRole('button', { name: 'Stop trend' }).click();
    await expect(chart.getByText(/manual stop/)).toBeVisible();
    const download = chart.getByRole('link', { name: 'Export entire capture CSV' });
    const href = await download.getAttribute('href');
    const csv = await (await page.request.get(href)).text();
    expect(csv.trim().split(/\r?\n/)).toHaveLength(41);
    await page.reload();
    await expect(chart.getByRole('link', { name: 'Export entire capture CSV' })).toHaveAttribute('href', href);
    await chart.getByRole('button', { name: 'Delete saved capture' }).click();
    await chart.getByRole('button', { name: 'Confirm delete capture' }).click();
    await expect(chart.getByRole('link', { name: 'Export entire capture CSV' })).toHaveCount(0);
    if (process.env.OPENHMI_TREND_SCREENSHOT) await chart.screenshot({ path: process.env.OPENHMI_TREND_SCREENSHOT });
  } finally {
    await save(original.active);
    await save(original.draft, false);
  }
});
