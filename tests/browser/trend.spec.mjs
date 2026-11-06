import { test, expect } from '@playwright/test';

test.use({ hasTouch: true });

async function save(page, project, apply = true) {
  const state = await (await page.request.get('/api/project')).json();
  const result = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
  expect(result.ok(), await result.text()).toBe(true);
  if (apply) {
    const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await result.json()).draft_revision } });
    expect(applied.ok(), await applied.text()).toBe(true);
  }
}

test('sparkline keeps live value and recent history quality separate', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  try {
    await save(page, { ...original.active, controls: [
      { id: 'level_spark', kind: 'sparkline', label: 'Tank history', tag: 'TankLevel', unit: '%', seconds: 30, decimals: 2 },
    ], layout: null });
    let unavailable = false;
    await page.route(url => url.pathname === '/api/history' && url.searchParams.get('tags') === 'TankLevel', route => {
      expect(route.request().url()).toContain('seconds=30');
      expect(route.request().url()).toContain('limit=1000');
      return route.fulfill(unavailable ? { status: 503 } : { json: {
        start: 100, end: 130, truncated: false,
        samples: [
          { epoch: 100, value: 10, quality: 'good' },
          { epoch: 105, value: 20, quality: 'good' },
          { epoch: 110, value: null, quality: 'bad' },
          { epoch: 120, value: 30, quality: 'good' },
          { epoch: 125, value: 40, quality: 'good' },
        ].map(sample => ({ ...sample, tag: 'TankLevel' })),
      } });
    });
    await page.goto('/runtime');
    const card = page.locator('[data-control="sparkline"]');
    const plot = card.getByRole('img', { name: 'Tank history, last 30 seconds' });
    const traces = plot.locator('polyline');
    await expect(traces).toHaveCount(2);
    await expect(card).toContainText('42.00 %');
    await expect(card).toContainText('Last 30 s');
    await expect(traces.nth(0)).toHaveAttribute('points', /^0,/);
    await expect(traces.nth(1)).toHaveAttribute('points', /^400,/);

    const live = await (await page.request.get('/api/tags')).json();
    live.samples.TankLevel = { quality: 'stale', age_seconds: 4 };
    await page.route('**/api/tags', route => route.fulfill({ json: live }));
    await expect(card).toContainText('STALE DATA');
    await expect(traces).toHaveCount(2);
    unavailable = true;
    await expect(card.getByRole('status')).toContainText('Showing last received history ending', { timeout: 10000 });
    await expect(traces).toHaveCount(2);
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('on-change trend holds prior values and leaves a gap after a missed heartbeat', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  try {
    const project = structuredClone(original.active);
    project.controls.push({ id: 'sparse_trend', kind: 'trend', label: 'On-change trend',
      tags: ['TankLevel', 'MotorRunning'], seconds: 10 });
    await save(page, project);
    let windowOffset = 0;
    let fault;
    await page.route(url => url.pathname === '/api/history' && url.searchParams.get('trend_context') === 'true',
      route => route.fulfill(fault ?? { json: {
        start: 100 + windowOffset, end: 110 + windowOffset, truncated: false,
        samples: [{ tag: 'TankLevel', epoch: 108, value: 20, quality: 'good' }],
        change_context: {
          TankLevel: { hold_seconds: 61, previous: { epoch: 45, value: 10, quality: 'good' } },
          MotorRunning: { hold_seconds: 61, previous: { epoch: 50, value: false, quality: 'good' } },
        },
      } }));
    await page.goto('/runtime');
    const chart = page.locator('[data-control="trend"]');
    const analog = chart.getByRole('img', { name: 'On-change trend trend', exact: true });
    const traces = analog.locator('[data-trend-tag="TankLevel"] polyline');
    await expect(traces).toHaveCount(2);
    await expect(traces.nth(0)).toHaveAttribute('points', '0,160 360,160');
    await expect(traces.nth(1)).toHaveAttribute('points', '480,0 600,0');
    await expect(chart.locator('[data-trend-lane="MotorRunning"] polyline')).toHaveAttribute('points', '0,23 600,23 600,23');
    const bounds = await analog.boundingBox();
    const atLevel = chart.locator('[data-trend-value="TankLevel"] [data-trend-cursor-value]');
    await analog.hover({ position: { x: bounds.width / 2, y: bounds.height / 2 } });
    await expect(atLevel).toHaveText('10.0');
    await expect(chart.locator('[data-trend-value="MotorRunning"] [data-trend-cursor-value]')).toHaveText('OFF');
    await analog.hover({ position: { x: bounds.width * 0.7, y: bounds.height / 2 } });
    await expect(atLevel).toHaveText('—');
    const lane = chart.getByRole('img', { name: 'MotorRunning Boolean history' });
    await lane.tap();
    const readout = chart.locator('[data-trend-cursor-time]');
    await expect(readout).toBeVisible();
    await expect(atLevel).toHaveText('10.0');
    const selectedTime = await readout.textContent();
    const marker = analog.locator('[data-trend-cursor]');
    const originalX = Number(await marker.getAttribute('x1'));
    windowOffset = 1;
    await expect.poll(async () => Number(await marker.getAttribute('x1'))).toBeCloseTo(originalX - 60);
    await expect(readout).toHaveText(selectedTime.trim());
    await expect(atLevel).toHaveText('10.0');
    await analog.hover({ position: { x: bounds.width / 4, y: bounds.height / 2 } });
    await expect(readout).toHaveText(selectedTime.trim());
    await chart.getByRole('button', { name: 'Clear trend cursor', exact: true }).tap();
    await expect(readout).toHaveCount(0);
    const timeline = chart.locator('.trend-plot');
    await timeline.press('ArrowRight');
    await expect(readout).toBeVisible();
    await timeline.press('Escape');
    await expect(readout).toHaveCount(0);
    await expect(chart.getByRole('link', { name: 'Export history CSV' })).not.toHaveAttribute('href', /trend_context/);
    const retained = await traces.nth(0).getAttribute('points');
    const warning = chart.getByRole('status').filter({ hasText: 'History unavailable' });
    fault = { json: { start: 101, end: 111, truncated: false, samples: [null] } };
    await expect(warning).toContainText('Showing last received history ending');
    await expect(traces.nth(0)).toHaveAttribute('points', retained);
    await expect(chart.locator('.trend-time')).toContainText('End');
    await expect(chart.locator('[data-trend-value="TankLevel"]')).toContainText('42.0');

    await chart.getByLabel('On-change trend history end').fill('2026-01-01T08:00');
    await expect(warning).toBeVisible();
    await expect(warning).not.toContainText('Showing last received history ending');
    await expect(traces).toHaveCount(0);
    fault = undefined;
    await expect(warning).toBeHidden();
    await expect(traces.nth(0)).toHaveAttribute('points', retained);
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('configure independent trend scales, live precision, and aligned Boolean lanes', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();

  try {
    const project = structuredClone(original.active);
    project.columns = 1;
    project.languages.push({ code: 'fr-FR', name: 'Français', flag: 'fr', translations: {
      'ui.trendTimeRangeLabel': 'Fenêtre de {label}', 'ui.trendCurrent': 'Valeur actuelle',
      'ui.trendRun': 'Démarrer la tendance', 'ui.trendStop': 'Arrêter la tendance',
      'ui.trendManualStop': 'arrêt manuel', 'ui.trendCursor': 'Curseur : {time}',
      'ui.trendExportCapture': 'Exporter la capture CSV',
      'ui.trendDeleteCapture': 'Supprimer la capture', 'ui.trendConfirmDelete': 'Confirmer la suppression',
    } });
    project.tags.push(
      { name: 'TrendLevel', type: 'number', initial: 42 },
      { name: 'TrendPressure', type: 'number', initial: 1050.25 },
      { name: 'TrendMotor', type: 'boolean', initial: true },
      { name: 'TrendAlarm', type: 'boolean', initial: false },
    );
    project.controls.push({ id: 'trend', kind: 'trend', label: 'Process trend', tags: ['TrendLevel'], seconds: 60 });
    await save(page, project);
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

    await page.getByRole('button', { name: 'Language: English', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Français', exact: true }).click();
    await expect(chart.getByLabel('Fenêtre de Process trend')).toHaveValue('17');
    await expect(chart.getByRole('columnheader', { name: 'Valeur actuelle' })).toBeVisible();
    await expect(chart.locator('[data-trend-value="TrendPressure"]')).toContainText('1050,25');
    await chart.locator('.trend-plot').press('ArrowRight');
    await expect(chart.locator('[data-trend-cursor-time]')).toContainText('Curseur :');
    await chart.locator('.trend-plot').press('Escape');
    await expect(chart.getByRole('link', { name: 'Export history CSV' })).toBeVisible();
    const endpoint = '**/api/trends/trend';
    const run = chart.getByRole('button', { name: 'Démarrer la tendance' });
    const stop = chart.getByRole('button', { name: 'Arrêter la tendance' });
    const statusWarning = chart.getByRole('status').filter({ hasText: 'Recording status unavailable' });
    let fault = { json: { enabled: true, captures: {} } };
    await page.route(endpoint, route => route.fulfill(fault));
    await expect(statusWarning).toBeVisible();
    await expect(run).toBeDisabled();
    await page.unroute(endpoint);
    await run.click();
    const retained = chart.getByText(/10 \/ 10 samples retained.*rolled off/);
    await expect(retained).toBeVisible();
    fault = { status: 503, json: { detail: 'Synthetic recording status outage' } };
    await page.route(endpoint, route => route.fulfill(fault));
    await expect(statusWarning).toContainText('Showing last received recording status');
    await expect(retained).toBeVisible();
    await expect(stop).toBeDisabled();
    await expect(run).toBeDisabled();
    await page.unroute(endpoint);
    await stop.click();
    await expect(chart.getByText(/arrêt manuel/)).toBeVisible();
    const download = chart.getByRole('link', { name: 'Exporter la capture CSV' });
    const href = await download.getAttribute('href');
    const csv = await (await page.request.get(href)).text();
    expect(csv.trim().split(/\r?\n/)).toHaveLength(41);
    await page.reload();
    await expect(download).toHaveAttribute('href', href);
    await chart.getByRole('button', { name: 'Supprimer la capture' }).click();
    const confirmDelete = chart.getByRole('button', { name: 'Confirmer la suppression' });
    fault = { json: { enabled: true, captures: [null] } };
    await page.route(endpoint, route => route.fulfill(fault));
    await expect(statusWarning).toBeVisible();
    await expect(confirmDelete).toBeDisabled();
    await expect(download).toHaveAttribute('href', href);
    await page.unroute(endpoint);
    await confirmDelete.click();
    await expect(download).toHaveCount(0);
    if (process.env.OPENHMI_TREND_SCREENSHOT) await chart.screenshot({ path: process.env.OPENHMI_TREND_SCREENSHOT });
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});
