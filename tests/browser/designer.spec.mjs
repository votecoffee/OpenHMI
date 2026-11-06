import { test, expect } from '@playwright/test';

test('no-code live editing, autosave, apply to an open viewer and Python action', async ({ page, context }) => {
  test.setTimeout(60000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('[data-control]')).toHaveCount(5);
  await expect(page.locator('[data-control="numeric"]')).toContainText('42.0');
  if (process.env.OPENHMI_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_SCREENSHOT, fullPage: true });
  const viewer = await context.newPage();
  viewer.on('pageerror', error => errors.push(error.message));
  await viewer.goto('/runtime');
  await expect(viewer.locator('[data-control]')).toHaveCount(5);
  const numericBox = await viewer.locator('[data-control="numeric"]').boundingBox();
  const indicatorBox = await viewer.locator('[data-control="indicator"]').boundingBox();
  expect(indicatorBox.x).toBeGreaterThan(numericBox.x);
  expect(Math.abs(indicatorBox.y - numericBox.y)).toBeLessThan(2);
  await page.locator('[data-control="numeric"]').click();
  await page.getByRole('textbox', { name: 'Label', exact: true }).fill('Live tank level');
  await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
  await expect(viewer.locator('[data-control="numeric"]')).toContainText('Tank level');
  await expect(viewer.locator('[data-control="numeric"]')).not.toContainText('Live tank level');
  await page.getByRole('button', { name: 'Apply live', exact: true }).click();
  await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
  await expect(viewer.locator('[data-control="numeric"]')).toContainText('Live tank level');
  await viewer.getByRole('button', { name: 'Toggle simulated motor', exact: true }).click();
  await expect(viewer.locator('[data-control="indicator"]')).toContainText('OFF');
  await expect(page.locator('[data-control="indicator"]')).toContainText('OFF');
  await expect(page.locator('[data-control="button"] button')).toBeDisabled();
  const block = page.getByRole('button', { name: 'Numeric display', exact: true });
  const source = await block.boundingBox();
  const target = await page.locator('.hmi-grid').boundingBox();
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
  await page.mouse.down();
  await page.mouse.move(target.x + 100, target.y + 90, { steps: 10 });
  await page.mouse.move(target.x + 110, target.y + 100, { steps: 2 });
  await page.mouse.up();
  await expect(page.locator('[data-control]')).toHaveCount(6);
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
  await page.reload();
  await expect(page.locator('[data-control]')).toHaveCount(6);
  await expect(viewer.locator('[data-control]')).toHaveCount(5);
  await page.route('**/api/tags', route => route.abort());
  await expect(page.locator('.app-header .connection')).toHaveText('Simulator disconnected');
  await expect(page.locator('[data-control="numeric"]').first()).toContainText('COMM LOSS');
  expect(errors).toEqual([]);
});

test('analog context, redundant alarm priority and data quality remain explicit', async ({ page }) => {
  let values = { TankLevel: 42.0, MotorRunning: true, ProcessAlarm: false };
  let alarms = { states: { process_alarm: { quality: 'good', condition: 0 } }, outstanding: [], active_count: 0, unacknowledged_count: 0 };
  await page.route('**/api/tags', route => route.fulfill({ json: { driver: 'simulator', values } }));
  await page.route('**/api/alarms', route => route.fulfill({ json: alarms }));
  await page.goto('/runtime');
  await expect(page.locator('[data-control="alarm"]')).toContainText('INACTIVE');
  await expect(page.getByLabel('Screen alarm status')).toContainText('No active or unacknowledged alarms');
  await expect(page.locator('[data-control="analog"]')).toContainText('Normal 20–80 %');
  if (process.env.OPENHMI_NORMAL_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_NORMAL_SCREENSHOT, fullPage: true });
  values = { TankLevel: 120.0, MotorRunning: false, ProcessAlarm: true };
  alarms = { ...alarms, active_count: 1, unacknowledged_count: 1, outstanding: [{ priority: 2, message: 'Process alarm', active: true }] };
  await expect(page.locator('[data-control="analog"]')).toContainText('120.0');
  await expect(page.locator('[data-control="analog"]')).toContainText('OUT OF SCALE');
  await expect(page.locator('[data-control="alarm"]')).toContainText('P2 ACTIVE');
  await expect(page.getByLabel('Screen alarm status')).toContainText('P2 Process alarm');
  await expect(page.locator('[data-control="alarm"] svg text')).toHaveText('2');
  await expect(page.locator('[data-control="indicator"]')).toContainText('OFF');
  if (process.env.OPENHMI_ALARM_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_ALARM_SCREENSHOT, fullPage: true });
  values = { TankLevel: 'bad', MotorRunning: null, ProcessAlarm: null };
  alarms = { ...alarms, states: { process_alarm: { quality: 'bad' } } };
  await expect(page.locator('[data-control="analog"]')).toContainText('BAD DATA');
  await expect(page.locator('[data-control="indicator"]')).toContainText('BAD DATA');
  await expect(page.getByLabel('Screen alarm status')).toContainText('BAD DATA');
  await expect(page.locator('[data-control="alarm"]')).not.toContainText('INACTIVE');
});

test('PLC route status and binding quality distinguish loss, stale data and recovery', async ({ page }) => {
  const configs = [
    { id: 'line', name: 'Line PLC', enabled: true },
    { id: 'utility', name: 'Utility PLC', enabled: true },
    { id: 'spare', name: 'Spare PLC', enabled: false },
  ];
  function withRoutes(project) {
    project.connections = configs;
    const button = project.controls.find(control => control.id === 'toggle');
    Object.assign(button, { mode: 'toggle', target: 'MotorRunning' });
  }
  await page.route('**/api/project', async route => {
    const response = await route.fetch(), data = await response.json();
    withRoutes(data.active);
    await route.fulfill({ response, json: data });
  });
  await page.route('**/api/project/active', async route => {
    const response = await route.fetch(), data = await response.json();
    withRoutes(data.project);
    await route.fulfill({ response, json: data });
  });

  const good = { quality: 'good' };
  const old = { timestamp: '2026-01-01T12:00:00Z', age_seconds: 3.25 };
  const values = { TankLevel: 42, MotorRunning: true, ProcessAlarm: false };
  const online = [{ id: 'line', connected: true }, { id: 'utility', connected: true }];
  let reachable = true;
  let live = { values, connections: online, samples: { TankLevel: good, MotorRunning: good } };
  await page.route('**/api/tags', route => reachable ? route.fulfill({ json: live }) : route.abort());
  await page.goto('/runtime');
  const header = page.locator('.app-header .connection');
  const station = page.locator('.station-mode');
  const numeric = page.locator('[data-control="numeric"]');
  const indicator = page.locator('[data-control="indicator"]');
  const button = page.getByRole('button', { name: 'Toggle simulated motor', exact: true });
  await expect(header).toContainText('PLC routes connected (2/2)');
  await expect(button).toBeEnabled();

  live = { ...live, connections: [{ id: 'line', connected: false, error: 'Timeout' }, online[1]],
    samples: { TankLevel: good, MotorRunning: { ...old, quality: 'bad', quality_reason: 'disconnected' } } };
  await expect(station).toContainText('PLC partial outage (1/2 connected)');
  await header.locator('summary').click();
  await expect(header.getByText('Runtime connected', { exact: true })).toBeVisible();
  await expect(header.getByText('Line PLC · Disconnected / retrying', { exact: true })).toBeVisible();
  await expect(header.getByText('Utility PLC · Connected', { exact: true })).toBeVisible();
  await expect(header.getByText('Spare PLC · Disabled', { exact: true })).toBeVisible();
  await expect(indicator).toContainText('PLC COMM LOSS');
  await expect(numeric).toContainText('42.0');
  await expect(button).toBeDisabled();

  live = { ...live, connections: online, samples: {
    TankLevel: { ...old, quality: 'stale', error: 'PLC sample is stale' },
    MotorRunning: { ...old, quality: 'bad', quality_reason: 'recovering' },
  } };
  await expect(numeric).toContainText('STALE DATA');
  await expect(numeric.getByText('3.3 s old', { exact: true })).toBeVisible();
  const quality = numeric.getByRole('button', { name: 'Inspect TankLevel quality (STALE DATA)' });
  await expect(quality).toHaveAttribute('title', /PLC sample is stale/);
  await quality.press('Enter');
  const qualityDetails = page.getByRole('dialog', { name: 'Tag quality details' });
  await expect(qualityDetails).toContainText('PLC sample is stale');
  await expect(qualityDetails).toContainText('Source time');
  await expect(qualityDetails).toContainText('3.3 s old');
  await page.keyboard.press('Escape');
  await expect(qualityDetails).toHaveCount(0);
  await expect(quality).toBeFocused();
  await quality.click();
  await expect(qualityDetails).toBeVisible();
  await qualityDetails.getByRole('button', { name: 'Close Tag quality details' }).click();
  await expect(numeric).not.toContainText('42.0');
  await expect(indicator).toContainText('WAITING FOR FRESH DATA');
  await expect(button).toBeDisabled();

  live = { ...live, plc_hold: true, connections: [], samples: {
    TankLevel: { quality: 'bad', quality_reason: 'held' },
    MotorRunning: { quality: 'bad', quality_reason: 'disabled' },
  } };
  await expect(station).toContainText('PLC acquisition held');
  await expect(numeric).toContainText('ACQUISITION HELD');
  await expect(indicator).toContainText('ROUTE DISABLED');

  reachable = false;
  await expect(station).toContainText('Runtime offline');
  await expect(numeric).toContainText('COMM LOSS');
  await expect(indicator).not.toContainText('ROUTE DISABLED');
  await expect(button).toBeDisabled();

  live = { values: { ...values, MotorRunning: false }, connections: online,
    samples: { TankLevel: good, MotorRunning: { quality: 'pending' } } };
  reachable = true;
  await expect(indicator).toContainText('WAITING FOR DATA');
  await expect(button).toBeDisabled();
  live = { ...live, samples: { TankLevel: good, MotorRunning: good } };
  await expect(indicator).toContainText('OFF');
  await expect(button).toBeEnabled();
});

test('stale editor keeps its local draft and cannot overwrite another writer', async ({ page, context }) => {
  const other = await context.newPage();
  await Promise.all([page.goto('/'), other.goto('/')]);
  await expect(page.locator('[data-control="numeric"]').first()).toBeVisible();
  await expect(other.locator('[data-control="numeric"]').first()).toBeVisible();
  await page.locator('[data-control="numeric"]').first().click();
  await page.getByRole('textbox', { name: 'Label', exact: true }).fill('Writer one');
  await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
  await other.locator('[data-control="numeric"]').first().click();
  await other.getByRole('textbox', { name: 'Label', exact: true }).fill('Writer two');
  await expect(other.getByRole('status', { name: 'Draft status' })).toContainText('Draft changed in another editor');
  await expect(other.locator('[data-control="numeric"]').first()).toContainText('Writer two');
  const state = await (await page.request.get('/api/project')).json();
  expect(state.draft.controls.find(control => control.kind === 'numeric').label).toBe('Writer one');
});
