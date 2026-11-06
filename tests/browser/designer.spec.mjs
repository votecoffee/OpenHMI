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
  const { active_revision: revision } = await (await page.request.get('/api/project')).json();
  let alarms = { sampled_revision: revision, states: {}, outstanding: [], active_count: 0, unacknowledged_count: 0 };
  let samples = {};
  await page.route('**/api/tags', route => route.fulfill({ json: { driver: 'simulator', values, samples } }));
  let alarmReachable = true;
  await page.route('**/api/alarms', route => alarmReachable ? route.fulfill({ json: alarms }) : route.abort());
  await page.goto('/runtime');
  await expect(page.locator('[data-control="alarm"]')).toContainText('INACTIVE');
  const banner = page.getByLabel('Screen alarm status');
  await expect(banner).toContainText('Waiting for alarm evaluation');
  await expect(banner).not.toContainText('No alarms configured');
  alarms = { ...alarms, states: { process_alarm: { quality: 'good', condition: 0 } } };
  await expect(banner).toContainText('No active or unacknowledged alarms');
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
  alarms = { ...alarms, evaluation_stale: true };
  await expect(banner).toContainText('Alarm evaluation is stale');
  await expect(banner).toContainText('P2 Process alarm');
  await expect(banner).toContainText('Last recorded: 1 active / 1 unacknowledged');
  alarmReachable = false;
  await expect(banner).toContainText('ALARM MONITOR UNAVAILABLE');
  await expect(banner).toContainText('P2 Process alarm');
  alarmReachable = true;
  alarms = { ...alarms, evaluation_stale: false };
  await expect(banner).not.toContainText('Last recorded');

  values = { TankLevel: 'bad', MotorRunning: null, ProcessAlarm: null };
  alarms = { ...alarms, states: { process_alarm: { quality: 'bad' } } };
  await expect(page.locator('[data-control="analog"]')).toContainText('BAD DATA');
  await expect(page.locator('[data-control="indicator"]')).toContainText('BAD DATA');
  alarms = { ...alarms, sampled_revision: revision - 1 };
  await expect(banner).toContainText('Waiting for alarm evaluation');
  await expect(banner).toContainText('P2 Process alarm');
  await expect(banner).not.toContainText('Unavailable alarm triggers');
  alarms = { ...alarms, sampled_revision: revision };
  const triggerWarning = banner.getByRole('link', { name: 'Unavailable alarm triggers (1)', exact: true });
  await expect(triggerWarning).toBeVisible();
  await expect(banner).toContainText('P2 Process alarm');
  await expect(page.locator('[data-control="alarm"]')).not.toContainText('INACTIVE');

  alarms = { ...alarms, active_count: 0, unacknowledged_count: 0, outstanding: [] };
  samples = { ProcessAlarm: { quality: 'bad', quality_reason: 'disconnected', error: 'Synthetic alarm source loss' } };
  await expect(banner).not.toContainText('P2 Process alarm');
  await expect(banner).not.toContainText('No active or unacknowledged alarms');
  await triggerWarning.click();
  const unavailable = page.getByRole('region', { name: 'Unavailable alarm triggers', exact: true });
  await expect(unavailable).toContainText('Process alarm');
  await expect(page.getByText('No recorded alarms in this view', { exact: true })).toBeVisible();
  await unavailable.getByRole('button', { name: 'Inspect ProcessAlarm quality (PLC COMM LOSS)', exact: true }).click();
  const triggerDetails = page.getByRole('dialog', { name: 'Tag quality details' });
  await expect(triggerDetails).toContainText('Synthetic alarm source loss');
  await page.keyboard.press('Escape');

  alarms = { ...alarms, states: { process_alarm: { quality: 'good', condition: 0 } } };
  await expect(unavailable).toHaveCount(0);
});

test('malformed alarm status keeps the last headline while the screen keeps updating', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const { active_revision: revision } = await (await page.request.get('/api/project')).json();
  const good = { sampled_revision: revision, states: { process_alarm: { quality: 'good' } },
    outstanding: [{ priority: 2, message: 'Process alarm', occurrence_id: 1 }], active_count: 1, unacknowledged_count: 1 };
  let alarms = {};
  let level = 42;
  await page.route('**/api/alarms', route => route.fulfill({ body: JSON.stringify(alarms), contentType: 'application/json' }));
  await page.route('**/api/tags', route => route.fulfill({ json: { values: { TankLevel: level } } }));
  await page.goto('/runtime');
  const banner = page.getByLabel('Screen alarm status');
  const numeric = page.locator('[data-control="numeric"]');
  await expect(banner).toContainText('ALARM MONITOR UNAVAILABLE');
  alarms = good;
  await expect(banner).toContainText('P2 Process alarm');
  await expect(banner).not.toContainText('Last recorded');

  for (const invalid of [null, { ...good, annunciated_outstanding: {} }, { ...good, outstanding: [null] },
    { ...good, active_count: '1' }, { ...good, states: { process_alarm: { quality: 'unknown' } } }]) {
    alarms = invalid;
    await expect(banner).toContainText('ALARM MONITOR UNAVAILABLE');
    await expect(banner).toContainText('P2 Process alarm');
    await expect(banner).toContainText('Last recorded: 1 active / 1 unacknowledged');
    level += 1;
    await expect(numeric).toContainText(level.toFixed(1));
    alarms = good;
    await expect(banner).not.toContainText('Last recorded');
    await expect(banner).toContainText('P2 Process alarm');
  }
  expect(errors).toEqual([]);
});

test('invalid tag replies fail closed and recover without reloading', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const good = { values: { TankLevel: 42, MotorRunning: true }, samples: { TankLevel: { quality: 'good' } }, connections: [] };
  let payload = good;
  await page.route('**/api/tags', route => route.fulfill({ body: JSON.stringify(payload), contentType: 'application/json' }));
  await page.goto('/runtime');
  const numeric = page.locator('[data-control="numeric"]');
  const header = page.locator('.app-header .connection');
  await expect(numeric).toContainText('42.0');

  payload = { ...good, samples: { TankLevel: null } };
  await expect(numeric).toContainText('BAD DATA');
  await expect(numeric).not.toContainText('42.0');
  await expect(header).toHaveText('Simulator connected');
  await expect(page.locator('[data-control="indicator"]')).toContainText('ON');

  payload = { ...good, samples: { TankLevel: { quality: 'stale', error: { reason: 'lost' }, timestamp: {} } } };
  await numeric.getByRole('button', { name: 'Inspect TankLevel quality (STALE DATA)' }).click();
  const details = page.getByRole('dialog', { name: 'Tag quality details' });
  await expect(details).toContainText('STALE DATA');
  await expect(details.getByText('PLC address', { exact: true })).toHaveCount(0);
  await page.keyboard.press('Escape');

  for (const invalid of [null, { ...good, values: [] }, { ...good, samples: [] }, { ...good, connections: [null] }]) {
    payload = invalid;
    await expect(header).toHaveText('Simulator disconnected');
    await expect(numeric).toContainText('COMM LOSS');
    payload = good;
    await expect(header).toHaveText('Simulator connected');
    await expect(numeric).toContainText('42.0');
  }
  expect(errors).toEqual([]);
});

test('invalid applied project replies preserve the open layout until a valid revision arrives', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const original = await (await page.request.get('/api/project/active')).json();
  const updated = { ...original, revision: original.revision + 1,
    project: { ...original.project, title: 'Updated layout after recovery' } };
  let status = original;
  let level = 42;
  await page.route('**/api/project/active', route => route.fulfill({ body: JSON.stringify(status), contentType: 'application/json' }));
  await page.route('**/api/tags', route => route.fulfill({ json: { values: { TankLevel: level } } }));
  await page.goto('/runtime');
  const oldRevision = page.getByText(`Live screen / revision ${original.revision}`, { exact: true });
  const oldTitle = page.getByRole('heading', { name: original.project.title, exact: true });
  const warning = page.getByText('Screen updates unavailable. Showing the last applied layout.');
  const numeric = page.locator('[data-control="numeric"]');
  await expect(numeric).toContainText('42.0');
  for (const invalid of [null, {}, { ...original, project_instance: 'damaged' },
    { ...updated, project: { ...updated.project, controls: [null] } },
    { ...updated, project: { ...updated.project, screens: [null] } },
    { ...updated, project: { ...updated.project, layout: { boxes: {} } } }]) {
    status = invalid;
    await expect(warning).toBeVisible();
    await expect(oldRevision).toBeVisible();
    await expect(oldTitle).toBeVisible();
    level += 1;
    await expect(numeric).toContainText(level.toFixed(1));
    status = original;
    await expect(warning).toBeHidden();
  }
  status = updated;
  await expect(page.getByRole('heading', { name: updated.project.title, exact: true })).toBeVisible();
  await expect(page.getByText(`Live screen / revision ${updated.revision}`, { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('a stalled recipe status request does not delay alarms, layout or identity', async ({ page }) => {
  let releaseRecipe;
  const recipePending = new Promise(resolve => { releaseRecipe = resolve; });
  let startedRecipe;
  const recipeStarted = new Promise(resolve => { startedRecipe = resolve; });
  await page.route('**/api/recipes/selected', async route => {
    startedRecipe();
    await recipePending;
    await route.continue();
  });
  const { active_revision: revision } = await (await page.request.get('/api/project')).json();
  const alarms = { sampled_revision: revision, states: { process_alarm: { quality: 'good', condition: 0 } },
    outstanding: [], active_count: 0, unacknowledged_count: 0 };
  let reachable = false;
  await page.route('**/api/alarms', route => reachable ? route.fulfill({ json: alarms }) : route.abort());
  await page.route('**/api/project/active', route => reachable ? route.continue() : route.abort());
  await page.route('**/api/security/session', route => reachable ? route.continue() : route.abort());
  try {
    await page.goto('/runtime');
    await recipeStarted;
    const banner = page.getByLabel('Screen alarm status');
    const layout = page.getByText('Screen updates unavailable. Showing the last applied layout.');
    const identity = page.getByText('HMI identity status unavailable.', { exact: false });
    await expect(layout).toBeVisible({ timeout: 3000 });
    await expect(identity).toBeVisible({ timeout: 3000 });
    await expect(banner).toContainText('ALARM MONITOR UNAVAILABLE');
    reachable = true;
    await expect(banner).toContainText('No active or unacknowledged alarms', { timeout: 3000 });
    await expect(layout).toBeHidden();
    await expect(identity).toBeHidden();
  } finally {
    releaseRecipe();
  }
});

test('one missing PLC tag is marked on its control while the same route keeps updating', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const { draft_revision } = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { project, expected_revision: draft_revision } });
    expect(saved.ok(), await saved.text()).toBe(true);
    if (apply) {
      const applied = await page.request.post('/api/project/apply', {
        data: { expected_revision: (await saved.json()).draft_revision },
      });
      expect(applied.ok(), await applied.text()).toBe(true);
    }
  }

  const project = {
    title: 'Single PLC binding fault',
    connections: [{ id: 'line', name: 'Synthetic PLC', path: 'offline-only/0', enabled: true }],
    tags: [
      { name: 'LineLevel', connection: 'line', address: 'LevelTypo', type: 'number' },
      { name: 'LineRunning', connection: 'line', address: 'Motor.Running', type: 'boolean' },
    ],
    controls: [
      { id: 'level', kind: 'numeric', label: 'Line level', tag: 'LineLevel', decimals: 1 },
      { id: 'running', kind: 'indicator', label: 'Line running', tag: 'LineRunning' },
    ],
  };

  try {
    await save(project);
    await page.goto('/runtime');
    const header = page.locator('.app-header .connection');
    const numeric = page.locator('[data-control="numeric"]').filter({ hasText: 'Line level' });
    const indicator = page.locator('[data-control="indicator"]');
    const badge = numeric.getByRole('button', { name: 'Inspect LineLevel quality (BAD DATA)', exact: true });
    await expect(indicator).toContainText('ON');
    await expect(header).toContainText('PLC routes connected (1/1)');
    await badge.click();
    const details = page.getByRole('dialog', { name: 'Tag quality details' });
    await expect(details).toContainText('LineLevel');
    await expect(details).toContainText('Synthetic PLC');
    await expect(details).toContainText('LevelTypo');
    await expect(details).toContainText('offline-only/0');
    await expect(details).toContainText('Tag does not exist');
    await page.keyboard.press('Escape');
    await expect(badge).toBeFocused();

    const snapshot = async () => (await (await page.request.get('/api/tags')).json()).samples;
    const first = await snapshot();
    expect(first.LineLevel).toMatchObject({ quality: 'bad', value: null });
    expect(first.LineRunning).toMatchObject({ quality: 'good', value: true });
    await expect.poll(async () => (await snapshot()).LineRunning.timestamp > first.LineRunning.timestamp).toBe(true);

    project.tags[0].address = 'Level';
    await save(project);
    await expect(numeric).toContainText('30.0');
    await expect(badge).toHaveCount(0);
    await expect(indicator).toContainText('ON');
    await expect(header).toContainText('PLC routes connected (1/1)');

    project.tags.push({ name: 'LineMotor', connection: 'line', address: 'Motor', type: 'struct', members: { MissingSpeed: 'number' } });
    project.controls.push({ id: 'speed', kind: 'numeric', label: 'Line speed', tag: 'LineMotor.MissingSpeed' });
    await save(project);
    const member = page.getByRole('button', { name: 'Inspect LineMotor.MissingSpeed quality (BAD DATA)', exact: true });
    await member.click();
    await expect(details.getByText('Motor.MissingSpeed', { exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
  } finally {
    await save(original.active);
    if (JSON.stringify(original.draft) !== JSON.stringify(original.active)) await save(original.draft, false);
  }
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
    Object.assign(button, { mode: 'toggle', target: 'MotorRunning', enabled_tag: 'ActionEnable' });
  }
  await page.route('**/api/project', async route => {
    const response = await route.fetch(), data = await response.json();
    withRoutes(data.active);
    await route.fulfill({ response, json: data });
  });
  const activeProject = await (await page.request.get('/api/project/active')).json();
  withRoutes(activeProject.project);
  await page.route('**/api/project/active', route => route.fulfill({ json: activeProject }));

  const good = { quality: 'good' };
  const old = { timestamp: '2026-01-01T12:00:00Z', age_seconds: 3.25 };
  const values = { TankLevel: 42, MotorRunning: true, ProcessAlarm: false, ActionEnable: true };
  const online = [{ id: 'line', connected: true }, { id: 'utility', connected: true }];
  let reachable = true;
  let live = { values, connections: [{ ...online[0], awaiting_data: true }, online[1]],
    samples: { TankLevel: good, MotorRunning: { quality: 'pending' } } };
  await page.route('**/api/tags', route => reachable ? route.fulfill({ json: live }) : route.abort());
  await page.goto('/runtime');
  const header = page.locator('.app-header .connection');
  const station = page.locator('.station-mode');
  const numeric = page.locator('[data-control="numeric"]');
  const indicator = page.locator('[data-control="indicator"]');
  const button = page.getByRole('button', { name: 'Toggle simulated motor', exact: true });
  await expect(header).toContainText('Waiting for initial PLC data');
  await header.locator('summary').click();
  await expect(header.getByText('Line PLC · Connected / waiting for first good data', { exact: true })).toBeVisible();
  await expect(header.getByText('Utility PLC · Connected', { exact: true })).toBeVisible();
  await header.locator('summary').click();
  live = { values, connections: online, samples: { TankLevel: good, MotorRunning: good } };
  await expect(header).toContainText('PLC routes connected (2/2)');
  await expect(button).toBeEnabled();

  live = { ...live, values: { ...values, ActionEnable: false } };
  await expect(page.getByText('Enable tag ActionEnable is off', { exact: true })).toBeVisible();
  await expect(button).toBeDisabled();
  live = { ...live, values, samples: { ...live.samples, ActionEnable: {
    quality: 'bad', quality_reason: 'disconnected', error: 'Synthetic enable route loss',
  } } };
  const enableQuality = page.getByRole('button', { name: 'Inspect ActionEnable quality (Enable tag · PLC COMM LOSS)', exact: true });
  await expect(button).toBeDisabled();
  await enableQuality.press('Enter');
  const enableDetails = page.getByRole('dialog', { name: 'Tag quality details' });
  await expect(enableDetails).toContainText('Synthetic enable route loss');
  await page.keyboard.press('Escape');
  await expect(enableQuality).toBeFocused();
  live = { ...live, samples: { TankLevel: good, MotorRunning: good } };
  await expect(button).toBeEnabled();

  live = { ...live, connections: [{ id: 'line', connected: false, error: 'Timeout' }, online[1]],
    samples: { TankLevel: good, MotorRunning: { ...old, quality: 'bad', quality_reason: 'disconnected' } } };
  await expect(station).toContainText('PLC partial outage (1/2 connected)');
  await header.locator('summary').click();
  await expect(header.getByText('Runtime connected', { exact: true })).toBeVisible();
  await expect(header.getByText('Line PLC · Disconnected / retrying', { exact: true })).toBeVisible();
  await expect(header.getByText('Utility PLC · Connected', { exact: true })).toBeVisible();
  await expect(header.getByText('Spare PLC · Disabled', { exact: true })).toBeVisible();
  live = { ...live, connections: [{ id: 'line', connected: true, scan_overdue: true }, online[1]] };
  await expect(header.getByText('Line PLC · Scan overdue', { exact: true })).toBeVisible();
  await expect(station).toContainText('PLC scan overdue');
  live = { ...live, connections: [{ id: 'line', connected: true, recovering: true }, online[1]] };
  await expect(station).toContainText('PLC recovery in progress');
  await expect(header.getByText('Line PLC · Reconnected / waiting for good data', { exact: true })).toBeVisible();
  await expect(header.getByText('Utility PLC · Connected', { exact: true })).toBeVisible();
  await expect(indicator).toContainText('PLC COMM LOSS');
  await expect(numeric).toContainText('42.0');
  await expect(button).toBeDisabled();

  live = { ...live, connections: [{ ...online[0], data_unavailable: true }, online[1]], samples: {
    TankLevel: { ...old, quality: 'stale', error: 'PLC sample is stale' },
    MotorRunning: { ...old, quality: 'bad', quality_reason: 'recovering' },
  } };
  await expect(station).toContainText('PLC data unavailable');
  await expect(header.getByText('Line PLC · Connected / no usable data', { exact: true })).toBeVisible();
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
