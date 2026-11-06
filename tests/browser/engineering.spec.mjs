import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('History panel exports recorded tags without a trend control', async ({ page }) => {
  test.setTimeout(120000);
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply) {
    const state = await (await page.request.get('/api/project')).json();
    const draft = await page.request.put('/api/project/draft', { data: { project, expected_revision: state.draft_revision } });
    expect(draft.ok(), await draft.text()).toBe(true);
    if (apply) expect((await page.request.post('/api/project/apply', {
      data: { expected_revision: (await draft.json()).draft_revision },
    })).ok()).toBe(true);
  }
  try {
    const project = structuredClone(original.active);
    project.historian.tags = ['TankLevel', 'MotorRunning'].map(tag => ({ tag, sample_ms: 100, deadband: 0 }));
    await save(project, true);
    await expect.poll(async () => {
      const response = await page.request.get('/api/history?tags=TankLevel&seconds=60');
      return (await response.json()).samples.length;
    }).toBeGreaterThan(0);
    await page.goto('/');
    await page.getByRole('button', { name: 'History', exact: true }).click();
    const panel = page.getByRole('group', { name: 'Export recorded data' });
    const button = panel.getByRole('button', { name: 'Download history CSV' });
    await expect(button).toBeDisabled();
    await panel.getByLabel('Include TankLevel', { exact: true }).check();
    await panel.getByRole('combobox', { name: 'Export time range', exact: true }).selectOption('60', { timeout: 10000 });
    const [file] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }), button.click()]);
    expect(file.suggestedFilename()).toBe('tag-history.csv');
    const csv = await readFile(await file.path(), 'utf8');
    expect(csv).toContain('tag,timestamp,value,quality,source_timestamp');
    expect(csv).toContain('TankLevel,');
    expect(csv).not.toContain('MotorRunning,');
    await expect(panel.getByRole('status')).toHaveText('CSV download started.');
    await panel.getByRole('combobox', { name: 'Export time range', exact: true }).selectOption('custom');
    await panel.getByRole('combobox', { name: 'Export time zone', exact: true }).selectOption('utc');
    const end = new Date(Date.now() + 1000);
    const start = new Date(end.getTime() - 60000);
    const startTime = panel.getByLabel('Export start time', { exact: true });
    const endTime = panel.getByLabel('Export end time', { exact: true });
    await startTime.fill(end.toISOString().slice(0, 19));
    await endTime.fill(start.toISOString().slice(0, 19));
    await button.click();
    await expect(panel.getByRole('status')).toHaveText('Start time must be before the end time.');
    await startTime.fill(start.toISOString().slice(0, 19));
    await endTime.fill(end.toISOString().slice(0, 19));
    const [exactRequest, exactFile] = await Promise.all([
      page.waitForRequest(request => request.url().includes('/api/history.csv?')),
      page.waitForEvent('download', { timeout: 15000 }),
      button.click(),
    ]);
    const bounds = new URL(exactRequest.url()).searchParams;
    expect(Number(bounds.get('start'))).toBe(Math.floor(start.getTime() / 1000));
    expect(Number(bounds.get('end'))).toBe(Math.floor(end.getTime() / 1000));
    expect(await readFile(await exactFile.path(), 'utf8')).toContain('TankLevel,');
    await panel.getByLabel('Export all retained rows in this range', { exact: true }).check();
    const [completeFile] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }), button.click()]);
    expect(completeFile.suggestedFilename()).toBe('tag-history.csv');
    expect(await readFile(await completeFile.path(), 'utf8')).toContain('TankLevel,');
    const logging = page.getByRole('combobox', { name: 'MotorRunning logging mode', exact: true });
    await expect(logging).toHaveValue('periodic');
    await logging.selectOption('change');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const state = await (await page.request.get('/api/project')).json();
    expect(state.active.historian.tags.find(item => item.tag === 'MotorRunning').mode).toBe('change');
    await page.getByRole('button', { name: 'Remove TankLevel', exact: true }).click();
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    await page.reload();
    await page.getByRole('button', { name: 'History', exact: true }).click();
    await expect(panel.getByRole('checkbox', { name: /^Include TankLevel/ })).toHaveCount(0);
    await panel.getByLabel('Recorded tag prefix', { exact: true }).fill('Tank');
    await panel.getByRole('button', { name: 'Find recorded tags', exact: true }).click();
    await panel.getByRole('checkbox', { name: 'Include TankLevel · Not in draft', exact: true }).check();
    const [retiredFile] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }), button.click()]);
    expect(await readFile(await retiredFile.path(), 'utf8')).toContain('TankLevel,');
  } finally {
    await save(original.active, true);
    await save(original.draft, false);
  }
});

test('UDT definition designer, multiple screens, popup actions and recorded trend', async ({ page, context }) => {
  test.setTimeout(180000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const original = await (await page.request.get('/api/project')).json();
  async function saveProject(project, apply = true) {
    const state = await (await page.request.get('/api/project')).json();
    const response = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
    expect(response.ok(), await response.text()).toBe(true);
    if (apply) expect((await page.request.post('/api/project/apply', { data: { expected_revision: (await response.json()).draft_revision } })).ok()).toBe(true);
  }
  async function drop(name) {
    await page.getByRole('button', { name, exact: true }).scrollIntoViewIfNeeded();
    const source = await page.getByRole('button', { name, exact: true }).boundingBox();
    const target = await page.locator('.hmi-grid').boundingBox();
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
    await page.mouse.down(); await page.mouse.move(target.x + 100, target.y + 90, { steps: 10 });
    await page.mouse.move(target.x + 110, target.y + 100, { steps: 2 }); await page.mouse.up();
  }
  try {
    const project = structuredClone(original.active);
    project.tags = [{ name: 'UnitA', type: 'struct', initial: { Speed: 12.5 }, members: { Speed: 'number' }, udt_type: 'GenericUnit', writable: true }];
    project.historian = { tags: [{ tag: 'UnitA.Speed', sample_ms: 100, deadband: 0 }, { tag: 'MotorRunning', sample_ms: 100, deadband: 0 }], retention_days: 30, max_rows: 1000 };
    await saveProject(project);
    await page.goto('/');
    await page.getByRole('button', { name: 'Connections', exact: true }).click();
    await page.getByLabel('Connection ID', { exact: true }).fill('testplc');
    await page.getByLabel('Connection name', { exact: true }).fill('Test PLC');
    await page.getByLabel('PLC route', { exact: true }).fill('offline-only/0');
    await page.getByRole('button', { name: 'Add connection', exact: true }).click();
    await page.getByRole('group', { name: 'Test PLC (testplc)', exact: true }).getByLabel('Enabled', { exact: true }).check();
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    await page.getByRole('button', { name: 'Tags', exact: true }).click();
    await page.getByRole('combobox', { name: 'Browse connection', exact: true }).selectOption('testplc');
    await page.getByRole('button', { name: 'Browse PLC tags', exact: true }).click();
    await page.getByRole('listbox', { name: 'PLC tag', exact: true }).selectOption('Level');
    const metadata = page.getByRole('group', { name: 'PLC tag metadata' });
    await expect(metadata).toContainText('PLC type REAL');
    await expect(metadata).toContainText('External access Read/Write');
    await expect(metadata).toContainText('PLC numeric range');
    await page.getByLabel('Logical tag name', { exact: true }).fill('PLCLevel');
    await page.getByRole('button', { name: 'Add tag', exact: true }).click();
    await page.getByLabel('PLCLevel scale', { exact: true }).fill('2');
    await page.getByLabel('PLCLevel offset', { exact: true }).fill('5');
    await page.getByRole('button', { name: 'History', exact: true }).click();
    await page.getByLabel('History tag', { exact: true }).fill('PLCLevel');
    await page.getByLabel('Sample interval (ms)', { exact: true }).fill('100');
    await page.getByRole('button', { name: 'Add history tag', exact: true }).click();
    await page.getByRole('button', { name: 'Faceplates', exact: true }).click();
    await page.getByLabel('Faceplate ID', { exact: true }).fill('Generic');
    await page.getByLabel('Faceplate name', { exact: true }).fill('Generic unit');
    await page.getByLabel('UDT type', { exact: true }).fill('GenericUnit');
    await page.getByLabel('Member path', { exact: true }).fill('Speed');
    await page.getByRole('combobox', { name: 'Member type', exact: true }).selectOption('number');
    await page.getByRole('button', { name: 'Add member', exact: true }).click();
    await page.getByRole('button', { name: 'Add faceplate definition', exact: true }).click();
    await page.getByRole('button', { name: 'Design Generic unit', exact: true }).click();
    await drop('Numeric display');
    await page.locator('[data-control="numeric"]').click();
    await page.getByRole('combobox', { name: 'Tag', exact: true }).selectOption({ label: '$.Speed' });
    await page.getByRole('textbox', { name: 'Label', exact: true }).fill('Unit speed');
    await page.getByRole('combobox', { name: 'Faceplate preview UDT', exact: true }).selectOption('UnitA');
    await expect(page.locator('[data-control="numeric"]')).toContainText('12.5');
    await page.getByRole('button', { name: 'Screens', exact: true }).click();
    await page.getByLabel('New screen ID', { exact: true }).fill('equipment');
    await page.getByLabel('New screen title', { exact: true }).fill('Equipment');
    await page.getByRole('button', { name: 'Add screen', exact: true }).click();
    await page.getByLabel('equipment update rate', { exact: true }).fill('200');
    await page.getByRole('button', { name: 'Edit Equipment', exact: true }).click();
    await drop('UDT faceplate');
    await expect(page.locator('[data-control="faceplate"]')).toContainText('Unit speed');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const latest = (await (await page.request.get('/api/project')).json()).active;
    expect(latest.screens[0].update_ms).toBe(200);
    const instance = latest.screens[0].controls.find(control => control.kind === 'faceplate');
    instance.enabled_tag = 'FaceplatePermit';
    latest.tags.push({ name: 'FaceplatePermit', type: 'boolean', initial: false, writable: true },
      { name: 'FaceplateOutput', type: 'boolean', initial: false, writable: true });
    const unit = latest.tags.find(tag => tag.name === 'UnitA');
    const template = latest.faceplates[0];
    const editMembers = { SpeedLow: 'number', SpeedHigh: 'number', Caption: 'string', CaptionLow: 'integer', CaptionHigh: 'integer' };
    Object.assign(unit.members, editMembers);
    Object.assign(template.members, editMembers);
    Object.assign(unit.initial, { SpeedLow: 10, SpeedHigh: 20, Caption: 'OK', CaptionLow: 2, CaptionHigh: 4 });
    template.controls.push(
      { id: 'unitOutput', kind: 'button', label: 'Toggle unit output', mode: 'toggle', target: 'FaceplateOutput' },
      { id: 'setpoint', kind: 'input', label: 'Unit setpoint', tag: '$.Speed', minimum_tag: '$.SpeedLow', maximum_tag: '$.SpeedHigh' },
      { id: 'caption', kind: 'text_input', label: 'Unit caption', tag: '$.Caption',
        min_length_tag: '$.CaptionLow', max_length_tag: '$.CaptionHigh' },
    );
    latest.screens[0].controls.push({ id: 'enableFaceplate', kind: 'button', label: 'Enable unit controls',
      mode: 'set', target: 'FaceplatePermit', value: true });
    latest.screens.push({ id: 'details', title: 'Details', popup: true, update_ms: 1000, columns: 1, controls: [{ id: 'trend', kind: 'trend', label: 'Speed history', tags: ['UnitA.Speed', 'PLCLevel', 'MotorRunning'], seconds: 60 }] });
    latest.screens.at(-1).controls.push({ id: 'more', kind: 'button', label: 'More details', mode: 'popup', screen: 'more' });
    latest.screens.push({ id: 'more', title: 'More', popup: true, update_ms: 500, columns: 1, controls: [
      { id: 'return', kind: 'button', label: 'Return to details', mode: 'close_popup' },
    ] });
    latest.screens[0].controls.push({ id: 'detailsButton', kind: 'button', label: 'Open details', mode: 'popup', screen: 'details' });
    await saveProject(latest);
    const viewer = await context.newPage();
    viewer.on('pageerror', error => errors.push(error.message));
    await viewer.goto('/runtime');
    await viewer.getByRole('button', { name: 'Equipment', exact: true }).click();
    await expect(viewer.locator('[data-control="faceplate"]')).toContainText('12.5');
    const output = viewer.getByRole('button', { name: 'Toggle unit output', exact: true });
    await expect(viewer.getByText('Enable tag FaceplatePermit is off', { exact: true })).toBeVisible();
    await expect(output).toBeDisabled();
    const blocked = await viewer.request.post(`/api/controls/equipment__${instance.id}__unitOutput/activate`, { data: {} });
    expect(blocked.status()).toBe(423);

    await viewer.route('**/api/tags', async route => {
      const response = await route.fetch();
      const state = await response.json();
      state.samples.FaceplatePermit = { quality: 'stale', error: 'Synthetic stale faceplate permit' };
      await route.fulfill({ response, json: state });
    });
    const permit = viewer.getByRole('button', { name: 'Inspect FaceplatePermit quality (Enable tag · STALE DATA)', exact: true });
    await expect(permit).toBeEnabled();
    await permit.click();
    const quality = viewer.getByRole('dialog', { name: 'Tag quality details', exact: true });
    await expect(quality).toContainText('Synthetic stale faceplate permit');
    await quality.getByRole('button', { name: 'Close Tag quality details' }).click();
    await expect(output).toBeDisabled();
    await viewer.unroute('**/api/tags');
    await viewer.getByRole('button', { name: 'Enable unit controls', exact: true }).click();
    await expect(output).toBeEnabled();
    await output.click();
    await expect.poll(async () => (await (await viewer.request.get('/api/tags')).json()).values.FaceplateOutput).toBe(true);

    const setpoint = viewer.locator('[data-control="input"]').filter({ hasText: 'Unit setpoint' });
    const caption = viewer.locator('[data-control="text_input"]').filter({ hasText: 'Unit caption' });
    await expect(setpoint).toContainText('Range: 10 – 20');
    await expect(caption).toContainText('Length: 2 – 4');
    const rejected = await viewer.request.put(`/api/controls/equipment__${instance.id}__setpoint/value`, { data: { value: 25 } });
    expect(rejected.status()).toBe(422);
    await setpoint.getByLabel('Unit setpoint new value', { exact: true }).fill('15');
    await setpoint.getByRole('button', { name: 'Write value', exact: true }).click();
    await caption.getByLabel('Unit caption new value', { exact: true }).fill('RUN');
    await caption.getByRole('button', { name: 'Write value', exact: true }).click();
    await expect.poll(async () => {
      const values = (await (await viewer.request.get('/api/tags')).json()).values;
      return [values['UnitA.Speed'], values['UnitA.Caption']];
    }).toEqual([15, 'RUN']);

    const open = viewer.getByRole('button', { name: 'Open details', exact: true });
    await open.press('Enter');
    const details = viewer.getByRole('dialog', { name: 'Details', exact: true });
    await expect(details.getByRole('button', { name: 'Close popup', exact: true })).toBeFocused();
    await expect(viewer.locator('[data-control="trend"] svg polyline').first()).toHaveAttribute('points', /[0-9]/);
    await expect(viewer.locator('[data-trend-lane="MotorRunning"] polyline')).toHaveAttribute('points', /[0-9]/);
    expect((await (await page.request.get('/api/tags')).json()).values.PLCLevel).toBe(65);
    if (process.env.OPENHMI_ENGINEERING_RUNTIME) await viewer.screenshot({ path: process.env.OPENHMI_ENGINEERING_RUNTIME, fullPage: true });
    const more = details.getByRole('button', { name: 'More details', exact: true });
    const subscribed = screens => viewer.waitForRequest(request => request.url().endsWith('/api/subscriptions')
      && request.method() === 'POST' && request.postDataJSON().screens.join(',') === screens);
    const [nestedSubscription] = await Promise.all([subscribed('equipment,details,more'), more.press('Enter')]);
    const nested = viewer.getByRole('dialog', { name: 'More', exact: true });
    await expect(nested.getByRole('button', { name: 'Close popup', exact: true })).toBeFocused();
    for (let index = 0; index < 5; index++) {
      await viewer.keyboard.press('Tab');
      expect(await viewer.evaluate(() => document.activeElement === document.body
        || document.activeElement.closest('dialog')?.getAttribute('aria-label') === 'More')).toBe(true);
    }
    const [parentSubscription] = await Promise.all([subscribed('equipment,details'),
      nested.getByRole('button', { name: 'Return to details', exact: true }).press('Enter')]);
    const nestedLease = nestedSubscription.postDataJSON();
    const parentLease = parentSubscription.postDataJSON();
    expect(parentLease.client).toBe(nestedLease.client);
    expect(parentLease.sequence).toBeGreaterThan(nestedLease.sequence);
    await expect(nested).toHaveCount(0);
    await expect(more).toBeFocused();
    await Promise.all([subscribed('equipment'), viewer.keyboard.press('Escape')]);
    await expect(viewer.getByRole('dialog')).toHaveCount(0);
    await expect(open).toBeFocused();
    await open.press('Enter');
    await details.getByRole('button', { name: 'Close popup', exact: true }).click();
    await expect(open).toBeFocused();
    await open.press('Enter');
    await Promise.all([subscribed('equipment,details,more'), more.press('Enter')]);
    const withoutNested = structuredClone(latest);
    withoutNested.screens = withoutNested.screens.filter(screen => screen.id !== 'more');
    withoutNested.screens.find(screen => screen.id === 'details').controls =
      withoutNested.screens.find(screen => screen.id === 'details').controls.filter(control => control.id !== 'more');
    await Promise.all([subscribed('equipment,details'), saveProject(withoutNested)]);
    await expect(nested).toHaveCount(0);
    await expect(details.getByRole('button', { name: 'Close popup', exact: true })).toBeFocused();
    await saveProject(latest);
    await expect(more).toBeVisible();
    await expect(nested).toHaveCount(0);
    await Promise.all([subscribed('equipment,details,more'), more.press('Enter')]);
    const withoutParent = structuredClone(latest);
    withoutParent.screens = withoutParent.screens.filter(screen => screen.id !== 'details');
    withoutParent.screens[0].controls = withoutParent.screens[0].controls.filter(control => control.id !== 'detailsButton');
    await Promise.all([subscribed('equipment'), saveProject(withoutParent)]);
    await expect(viewer.getByRole('dialog')).toHaveCount(0);
    await expect(viewer.getByRole('button', { name: 'Equipment', exact: true })).toBeFocused();
    await viewer.reload();
    await expect(viewer.locator('[data-control="faceplate"]')).toContainText('Unit speed');
    await saveProject(latest);
    await expect(open).toBeVisible();
    await Promise.all([subscribed('equipment,details'), open.press('Enter')]);
    const withoutEquipment = structuredClone(latest);
    withoutEquipment.screens = withoutEquipment.screens.filter(screen => screen.id !== 'equipment');
    await Promise.all([subscribed('overview'), saveProject(withoutEquipment)]);
    const overview = viewer.getByRole('button', { name: latest.title, exact: true });
    await expect(viewer.getByRole('dialog')).toHaveCount(0);
    await expect(overview).toBeFocused();
    await expect(overview).toHaveAttribute('aria-pressed', 'true');
    await expect(viewer).toHaveURL(/\/runtime$/);
    await saveProject(latest);
    await expect(viewer.getByRole('button', { name: 'Equipment', exact: true })).toBeVisible();
    await expect(overview).toHaveAttribute('aria-pressed', 'true');
    await viewer.goto('/runtime?screen=details&station=review#view');
    await expect(viewer).toHaveURL(/\/runtime\?station=review#view$/);
    await expect(overview).toHaveAttribute('aria-pressed', 'true');
    expect(errors).toEqual([]);
  } finally {
    await saveProject(original.active);
    await saveProject(original.draft, false);
  }
});

test('PLC browse keeps a delayed response from replacing the selected connection', async ({ page }) => {
  await page.route('**/api/project', async route => {
    const response = await route.fetch();
    const project = await response.json();
    project.draft.connections = ['first', 'second'].map(id => ({ id, name: id, path: 'offline-only/0', enabled: false }));
    await route.fulfill({ response, json: project });
  });
  let release;
  const delayed = new Promise(resolve => { release = resolve; });
  await page.route('**/api/connections/first/browse', async route => {
    await delayed;
    await route.fulfill({ json: { tags: [{ address: 'Previous', type: 'number', plc_type: 'REAL' }] } });
  });
  await page.route('**/api/connections/second/browse', route => route.fulfill({ json: { tags: [{
    address: 'Current', type: 'string', plc_type: 'ShortString', external_access: 'Read Only',
    dimensions: [3, 0, 0], string_capacity_bytes: 24,
  }] } }));

  try {
    await page.goto('/');
    await page.getByRole('button', { name: 'Tags', exact: true }).click();
    const connection = page.getByRole('combobox', { name: 'Browse connection', exact: true });
    const browse = page.getByRole('button', { name: 'Browse PLC tags', exact: true });
    await connection.selectOption('first');
    const pending = page.waitForRequest('**/api/connections/first/browse');
    await browse.click();
    await pending;
    await connection.selectOption('second');
    await expect(page.getByLabel('PLC address', { exact: true })).toHaveValue('');
    await browse.click();
    const tags = page.getByRole('listbox', { name: 'PLC tag', exact: true });
    await tags.selectOption('Current');

    const response = page.waitForResponse('**/api/connections/first/browse');
    release();
    await (await response).finished();
    const metadata = page.getByRole('group', { name: 'PLC tag metadata' });
    await expect(metadata).toContainText('External access Read Only');
    await expect(metadata).toContainText('Array dimensions 3');
    await expect(metadata).toContainText('PLC STRING capacity 24 bytes');
    await expect(tags).toHaveValue('Current');
    await expect(tags.getByRole('option', { name: /Previous/ })).toHaveCount(0);
  } finally {
    release();
  }
});
