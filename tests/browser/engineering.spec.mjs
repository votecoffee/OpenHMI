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
    latest.screens.push({ id: 'details', title: 'Details', popup: true, update_ms: 1000, columns: 1, controls: [{ id: 'trend', kind: 'trend', label: 'Speed history', tags: ['UnitA.Speed', 'PLCLevel', 'MotorRunning'], seconds: 60 }] });
    latest.screens[0].controls.push({ id: 'detailsButton', kind: 'button', label: 'Open details', mode: 'popup', screen: 'details' });
    await saveProject(latest);
    const viewer = await context.newPage();
    viewer.on('pageerror', error => errors.push(error.message));
    await viewer.goto('/runtime');
    await viewer.getByRole('button', { name: 'Equipment', exact: true }).click();
    await expect(viewer.locator('[data-control="faceplate"]')).toContainText('12.5');
    await viewer.getByRole('button', { name: 'Open details', exact: true }).click();
    await expect(viewer.getByRole('dialog', { name: 'Details', exact: true })).toBeVisible();
    await expect(viewer.locator('[data-control="trend"] svg polyline').first()).toHaveAttribute('points', /[0-9]/);
    await expect(viewer.locator('[data-trend-lane="MotorRunning"] polyline')).toHaveAttribute('points', /[0-9]/);
    expect((await (await page.request.get('/api/tags')).json()).values.PLCLevel).toBe(65);
    if (process.env.OPENHMI_ENGINEERING_RUNTIME) await viewer.screenshot({ path: process.env.OPENHMI_ENGINEERING_RUNTIME, fullPage: true });
    await viewer.getByRole('button', { name: 'Close popup', exact: true }).click();
    await expect(viewer.getByRole('dialog')).toHaveCount(0);
    await viewer.reload();
    await expect(viewer.locator('[data-control="faceplate"]')).toContainText('Unit speed');
    expect(errors).toEqual([]);
  } finally {
    await saveProject(original.active);
    await saveProject(original.draft, false);
  }
});
