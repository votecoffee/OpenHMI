import { test, expect } from '@playwright/test';

test('trend source failures retain only matching traces and captures without replaying recording commands', async ({ page }) => {
  test.setTimeout(90000);
  const errors = [], commands = [];
  page.on('pageerror', error => errors.push(error.message));
  const original = await (await page.request.get('/api/project')).json();
  async function install(project) {
    const state = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
    expect(saved.ok()).toBe(true);
    expect((await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } })).ok()).toBe(true);
  }
  let historyMode = 'same', statusMode = 'same';
  const headers = mode => mode === 'missing' ? {} : { 'X-OpenHMI-Project': mode === 'same' ? original.project_instance : 'f'.repeat(32) };
  const project = structuredClone(original.active);
  project.controls = [{ id: 'identity_trend', kind: 'trend', label: 'Identity trend', tags: ['TankLevel'], seconds: 30,
    recording: { sample_ms: 100, max_samples: 20 } }];
  project.layout = null;
  try {
    await install(project);
    const historyRoute = async route => {
      if (historyMode === 'denied') return route.fulfill({ status: 403, body: 'Forbidden', contentType: 'text/plain' });
      const seconds = Number(new URL(route.request().url()).searchParams.get('seconds'));
      const end = 1800000000, start = end - seconds;
      const values = historyMode === 'same' ? [10, 20] : [10, 9876, 20];
      return route.fulfill({ headers: headers(historyMode), json: { start, end, truncated: false,
        samples: values.map((value, index) => ({ tag: 'TankLevel', epoch: start + seconds * index / (values.length - 1), value, quality: 'good' })) } });
    };
    await page.route('**/api/history?*', historyRoute);
    await page.route(/\/api\/trend-captures\/[1-9]\d*\?/, historyRoute);
    await page.route('**/api/trends/identity_trend', async route => {
      if (route.request().method() !== 'GET') return route.continue();
      if (statusMode === 'denied') return route.fulfill({ status: 403, body: 'Forbidden', contentType: 'text/plain' });
      const response = await route.fetch();
      const data = await response.json();
      return route.fulfill({ headers: headers(statusMode), json: statusMode === 'same' ? data : {
        ...data, captures: data.captures.map(capture => ({ ...capture, reason: 'FOREIGN RECORDING', stopped: capture.started })) } });
    });
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/trends/identity_trend') commands.push(request.postDataJSON().action);
    });
    await page.goto('/runtime');
    const chart = page.locator('[data-control="trend"]');
    const run = chart.getByRole('button', { name: 'Run trend', exact: true });
    const stop = chart.getByRole('button', { name: 'Stop trend', exact: true });
    const trace = chart.locator('[data-trend-tag="TankLevel"] polyline');
    const historyWarning = chart.getByRole('status').filter({ hasText: 'History unavailable' });
    const statusWarning = chart.getByRole('status').filter({ hasText: 'Recording status unavailable' });
    await expect(trace).toHaveAttribute('points', '0,160 600,0');
    await expect(run).toBeEnabled();
    await run.click();
    await expect(stop).toBeEnabled();
    const download = chart.getByRole('link', { name: 'Export entire capture CSV', exact: true });
    const captureHref = await download.getAttribute('href');
    for (const mode of ['foreign', 'missing']) {
      statusMode = mode;
      await expect(statusWarning).toContainText('Showing last received recording status');
      await expect(run).toBeDisabled();
      await expect(stop).toBeDisabled();
      await expect(download).toHaveAttribute('href', captureHref);
      await expect(chart).not.toContainText('FOREIGN RECORDING');
      await expect(historyWarning).toHaveCount(0);
      statusMode = 'same';
      await expect(statusWarning).toHaveCount(0);
      await expect(stop).toBeEnabled();
      historyMode = mode;
      await expect(historyWarning).toContainText('Showing last received history ending');
      await expect(trace).toHaveAttribute('points', '0,160 600,0');
      await expect(stop).toBeEnabled(); // Healthy recording status remains independent of history.
      await expect(chart.locator('[data-trend-value="TankLevel"]')).toContainText('42.0');
      historyMode = 'same';
      await expect(historyWarning).toHaveCount(0);
    }
    expect(commands).toEqual(['start']);
    historyMode = 'foreign';
    await chart.getByLabel('Identity trend time range', { exact: true }).selectOption('10');
    await expect(historyWarning).toBeVisible();
    await expect(historyWarning).not.toContainText('Showing last received history ending');
    await expect(trace).toHaveCount(0);
    historyMode = 'same';
    await expect(trace).toHaveAttribute('points', '0,160 600,0');
    historyMode = 'denied';
    await expect(historyWarning).toBeVisible();
    await expect(trace).toHaveCount(0);
    historyMode = 'same';
    await expect(trace).toHaveAttribute('points', '0,160 600,0');
    statusMode = 'denied';
    await expect(statusWarning).toBeVisible();
    await expect(download).toHaveCount(0);
    await expect(stop).toBeDisabled();
    statusMode = 'same';
    await expect(download).toHaveAttribute('href', captureHref);
    await expect(stop).toBeEnabled();
    await stop.click();
    await expect(run).toBeEnabled();
    await chart.getByRole('button', { name: 'Delete saved capture', exact: true }).click();
    const confirm = chart.getByRole('button', { name: 'Confirm delete capture', exact: true });
    statusMode = 'foreign';
    await expect(statusWarning).toBeVisible();
    await expect(confirm).toBeDisabled();
    await expect(download).toHaveAttribute('href', captureHref);
    expect(commands).toEqual(['start', 'stop']);
    statusMode = 'same';
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(download).toHaveCount(0);
    expect(commands).toEqual(['start', 'stop', 'delete']);
    expect(errors).toEqual([]);
  } finally {
    await page.unroute('**/api/trends/identity_trend');
    const status = await (await page.request.get('/api/trends/identity_trend')).json();
    const running = status.captures.find(capture => capture.stopped === null);
    if (running) await page.request.post('/api/trends/identity_trend', { data: { action: 'stop', capture_id: running.id } });
    await install(original.active);
    const state = await (await page.request.get('/api/project')).json();
    await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project: original.draft } });
  }
});
