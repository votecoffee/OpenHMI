import { test, expect } from '@playwright/test';

const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jX1sAAAAASUVORK5CYII=', 'base64');

async function save(page, project, apply = true) {
  const state = await (await page.request.get('/api/project')).json();
  const response = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
  expect(response.ok(), await response.text()).toBe(true);
  if (apply) {
    const result = await page.request.post('/api/project/apply', { data: { expected_revision: (await response.json()).draft_revision } });
    expect(result.ok(), await result.text()).toBe(true);
  }
}

test('compact annotations, LED and setpoint displays survive canvas save and live apply', async ({ page }) => {
  test.setTimeout(60000);
  const original = await (await page.request.get('/api/project')).json();
  try {
    await save(page, { ...original.active, controls: [], screens: [], layout: null,
      tags: [{ name: 'Highlight', type: 'boolean', initial: true }, { name: 'PanelValue', type: 'number', initial: -4.2 },
        { name: 'ProcessSample', type: 'number', initial: 1.1 }, { name: 'CompareSetpoint', type: 'number', initial: 1 },
        { name: 'CompareTolerance', type: 'number', initial: 0.1 }] });
    await page.goto('/');
    await page.getByRole('button', { name: 'Enable freeform layout' }).click();
    const canvas = page.getByLabel('Freeform canvas', { exact: true });
    const palette = page.getByRole('group', { name: 'Control palette' });
    const type = palette.getByRole('combobox', { name: 'Control type' });
    const source = palette.getByRole('button', { name: 'Add or drag control' });
    const fields = page.getByRole('group', { name: 'Control properties' });

    await type.selectOption('StaticLabel');
    await source.dragTo(canvas, { targetPosition: { x: 24, y: 40 } });
    await expect(canvas.locator('.canvas-selected')).toHaveCSS('height', '32px');
    await fields.getByRole('textbox', { name: 'Label', exact: true }).fill('Part exit');
    await fields.getByRole('spinbutton', { name: 'Font size (px)', exact: true }).fill('18');
    await fields.getByRole('combobox', { name: 'Text weight', exact: true }).selectOption({ label: 'Bold' });
    await fields.getByRole('combobox', { name: 'Text alignment', exact: true }).selectOption({ label: 'Center' });

    await type.selectOption('ScreenSymbol');
    await source.dragTo(canvas, { targetPosition: { x: 192, y: 40 } });
    await expect(canvas.locator('.canvas-selected')).toHaveCSS('height', '48px');
    await fields.getByRole('textbox', { name: 'Accessible label', exact: true }).fill('Exit direction');
    await fields.getByRole('combobox', { name: 'Rotation', exact: true }).selectOption({ label: '90 degrees' });
    await fields.getByRole('combobox', { name: 'Color when tag is true', exact: true }).selectOption({ label: 'Highlight' });

    await type.selectOption('LedDisplay');
    await source.dragTo(canvas, { targetPosition: { x: 264, y: 40 } });
    await expect(canvas.locator('.canvas-selected')).toHaveCSS('height', '64px');
    await fields.getByRole('combobox', { name: 'Tag', exact: true }).selectOption({ label: 'PanelValue' });
    await fields.getByRole('spinbutton', { name: 'Digit positions', exact: true }).fill('3');
    await fields.getByRole('textbox', { name: 'Units', exact: true }).fill('psi');

    await type.selectOption('SetpointComparison');
    await source.dragTo(canvas, { targetPosition: { x: 456, y: 40 } });
    await fields.getByRole('combobox', { name: 'Process value tag', exact: true }).selectOption({ label: 'ProcessSample' });
    await fields.getByRole('combobox', { name: 'Setpoint tag', exact: true }).selectOption({ label: 'CompareSetpoint' });
    await fields.getByRole('combobox', { name: 'Tolerance from tag', exact: true }).selectOption({ label: 'CompareTolerance' });
    await fields.getByRole('textbox', { name: 'Units', exact: true }).fill('bar');

    await page.getByRole('button', { name: 'Save draft', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');

    await page.goto('/runtime');
    const label = page.locator('[data-control="label"]');
    const arrow = page.getByRole('img', { name: 'Exit direction', exact: true });
    await expect(label).toHaveText('Part exit');
    await expect(label).toHaveCSS('font-size', '18px');
    await expect(label).toHaveCSS('font-weight', '700');
    await expect(label).toHaveCSS('text-align', 'center');
    await expect(arrow.locator('path')).toHaveAttribute('transform', 'rotate(90 12 12)');
    await expect(arrow).toHaveCSS('color', 'rgb(0, 40, 120)');
    const { active } = await (await page.request.get('/api/project')).json();
    expect(active.controls.map(control => control.kind)).toEqual(['label', 'symbol', 'led_display', 'setpoint_comparison']);
    expect(active.controls.slice(0, 2).every(control => !Object.hasOwn(control, 'tag'))).toBe(true);

    const display = page.locator('[data-control="led_display"]');
    const reading = display.getByRole('img', { name: 'Numeric readout -4.2 psi', exact: true });
    await expect(reading.locator('g')).toHaveCount(3);
    await expect(reading.locator('g').nth(0).locator('.led-lit')).toHaveCount(1);
    await expect(reading.locator('g').nth(1).locator('.led-dot')).toHaveCount(1);
    const comparison = page.locator('[data-control="setpoint_comparison"]');
    await expect(comparison).toContainText('+0.1 bar');
    await expect(comparison).toContainText('Within tolerance');
    const live = await (await page.request.get('/api/tags')).json();
    live.values.PanelValue = 99.96;
    live.values.ProcessSample = 1.2;
    await page.route('**/api/tags', route => route.fulfill({ json: live }));
    await expect(comparison).toContainText('Outside tolerance');
    await expect(comparison).toContainText('+0.2 bar');
    live.samples.CompareSetpoint = { quality: 'stale', age_seconds: 4 };
    await expect(comparison).toContainText('Comparison unavailable');
    await expect(comparison).toContainText('STALE DATA');
    await expect(comparison).toContainText('1.2 bar');
    await expect(comparison).not.toContainText('+0.2 bar');
    live.samples.CompareSetpoint = { quality: 'good' };
    live.samples.CompareTolerance = { quality: 'bad', error: 'Test tolerance unavailable' };
    await expect(comparison).toContainText('BAD DATA');
    await expect(comparison).toContainText('+0.2 bar');
    await expect(comparison).toContainText('Comparison unavailable');
    await expect(display).toContainText('DISPLAY OVERFLOW');
    await expect(display).toContainText('99.96 psi');
    await expect(display.getByRole('img')).toHaveCount(0);
    live.samples.PanelValue = { quality: 'stale', age_seconds: 4 };
    await expect(display).toContainText('STALE DATA');
    await expect(display).not.toContainText('DISPLAY OVERFLOW');
    live.samples.PanelValue = { quality: 'good' };
    live.values.PanelValue = -0.04;
    await expect(display.getByRole('img', { name: 'Numeric readout 0.0 psi', exact: true })).toBeVisible();
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('state, position and rotation images follow tags and quality', async ({ page }) => {
  test.setTimeout(60000);
  const other = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAE0lEQVR4nGM0Di1ngAEmOAsvBwAyjgEHv03a3gAAAABJRU5ErkJggg==', 'base64');
  const original = await (await page.request.get('/api/project')).json();
  try {
    await save(page, { ...original.active, controls: [], screens: [], layout: null,
      tags: [{ name: 'ValveOpen', type: 'boolean', initial: true }, { name: 'FixtureState', type: 'integer', initial: 1 },
        { name: 'AxisTravel', type: 'number', initial: 25 }, { name: 'ValveAngle', type: 'number', initial: 25 }] });
    await page.goto('/');
    await page.getByRole('button', { name: 'Enable freeform layout' }).click();
    const canvas = page.getByLabel('Freeform canvas', { exact: true });
    const palette = page.getByRole('group', { name: 'Control palette' });
    await palette.getByRole('combobox', { name: 'Control type' }).selectOption('StateImage');
    await palette.getByRole('button', { name: 'Add or drag control' }).dragTo(canvas, { targetPosition: { x: 24, y: 40 } });
    const fields = page.getByRole('group', { name: 'Control properties' });
    await fields.getByRole('combobox', { name: 'Tag', exact: true }).selectOption({ label: 'ValveOpen' });
    await fields.getByRole('textbox', { name: 'Label', exact: true }).fill('Valve');
    await fields.getByRole('textbox', { name: 'ON text', exact: true }).fill('Open');
    await fields.getByRole('textbox', { name: 'OFF text', exact: true }).fill('Closed');
    await fields.getByRole('combobox', { name: 'Show label and state text', exact: true }).selectOption({ label: 'No' });
    for (const [state, buffer] of [['ON', pixel], ['OFF', other]]) {
      const image = fields.getByRole('group', { name: state + ' image', exact: true });
      await image.getByLabel('Upload ' + state + ' image').setInputFiles({ name: state + '.png', mimeType: 'image/png', buffer });
      await expect(image.getByRole('img', { name: 'Uploaded image preview' })).toHaveJSProperty('complete', true);
      await image.getByRole('button', { name: 'Use uploaded image', exact: true }).click();
    }

    await palette.getByRole('combobox', { name: 'Control type' }).selectOption('MultiStateImage');
    await palette.getByRole('button', { name: 'Add or drag control' }).dragTo(canvas, { targetPosition: { x: 216, y: 40 } });
    await fields.getByRole('combobox', { name: 'Tag', exact: true }).selectOption({ label: 'FixtureState' });
    await fields.getByRole('textbox', { name: 'Label', exact: true }).fill('Fixture');
    await fields.getByRole('combobox', { name: 'Show label and state text', exact: true }).selectOption({ label: 'No' });
    const rows = fields.getByRole('group', { name: 'State images', exact: true });
    await rows.getByRole('button', { name: 'Add state', exact: true }).click();
    for (const [index, label, buffer] of [[2, 'Clamping', pixel], [3, 'Released', other]]) {
      const row = rows.getByRole('group', { name: 'State ' + index, exact: true });
      await row.getByRole('textbox', { name: 'State label', exact: true }).fill(label);
      await row.getByLabel('Upload Image', { exact: true }).setInputFiles({ name: label + '.png', mimeType: 'image/png', buffer });
      await row.getByRole('button', { name: 'Use uploaded image', exact: true }).click();
    }
    await palette.getByRole('combobox', { name: 'Control type' }).selectOption('PositionImage');
    await palette.getByRole('button', { name: 'Add or drag control' }).dragTo(canvas, { targetPosition: { x: 400, y: 40 } });
    await fields.getByRole('combobox', { name: 'Tag', exact: true }).selectOption({ label: 'AxisTravel' });
    await fields.getByRole('textbox', { name: 'Units', exact: true }).fill('mm');
    await fields.getByRole('combobox', { name: 'Travel direction', exact: true }).selectOption({ label: 'Right to left' });
    await fields.getByRole('combobox', { name: 'Show label and state text', exact: true }).selectOption({ label: 'No' });
    const travelImage = fields.getByRole('group', { name: 'Motion image', exact: true });
    await travelImage.getByLabel('Upload Motion image', { exact: true }).setInputFiles({ name: 'Carriage.png', mimeType: 'image/png', buffer: other });
    await travelImage.getByRole('button', { name: 'Use uploaded image', exact: true }).click();
    await palette.getByRole('combobox', { name: 'Control type' }).selectOption('RotationImage');
    await palette.getByRole('button', { name: 'Add or drag control' }).dragTo(canvas, { targetPosition: { x: 640, y: 40 } });
    await fields.getByRole('combobox', { name: 'Tag', exact: true }).selectOption({ label: 'ValveAngle' });
    await fields.getByRole('spinbutton', { name: 'Start angle (degrees)', exact: true }).fill('90');
    await fields.getByRole('spinbutton', { name: 'End angle (degrees)', exact: true }).fill('-90');
    await fields.getByRole('combobox', { name: 'Show label and state text', exact: true }).selectOption({ label: 'No' });
    await travelImage.getByLabel('Upload Motion image', { exact: true }).setInputFiles({ name: 'Valve.png', mimeType: 'image/png', buffer: other });
    await travelImage.getByRole('button', { name: 'Use uploaded image', exact: true }).click();
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const { active } = await (await page.request.get('/api/project')).json();
    const image = active.controls[0];
    expect(image.on_image).toMatch(/^[a-f0-9]{64}$/);
    expect(image.off_image).toMatch(/^[a-f0-9]{64}$/);
    expect(image.off_image).not.toBe(image.on_image);

    await page.goto('/runtime');
    const control = page.locator('[data-control="state_image"]');
    const opened = control.getByRole('img', { name: 'Valve: Open', exact: true });
    await expect(opened).toHaveAttribute('src', '/api/canvas-images/' + image.on_image);
    await expect(opened).toHaveJSProperty('naturalWidth', 1);
    const multi = page.locator('[data-control="multi_state_image"]');
    await expect(multi.getByRole('img', { name: 'Fixture: Clamping', exact: true })).toHaveJSProperty('naturalWidth', 1);
    const position = page.locator('[data-control="position_image"]');
    const marker = position.locator('.motion-marker');
    const track = position.locator('.motion-travel');
    await expect(position.getByRole('img', { name: 'Axis position: 25.0 mm', exact: true })).toHaveJSProperty('naturalWidth', 4);
    const offset = async () => {
      const path = await track.boundingBox(), point = await marker.boundingBox();
      return (point.x - path.x) / (path.width - point.width);
    };
    await expect.poll(offset).toBeCloseTo(0.75);
    const rotation = page.locator('[data-control="rotation_image"]');
    const rotor = rotation.locator('.motion-marker');
    const turn = () => rotor.evaluate(element => {
      const matrix = new DOMMatrixReadOnly(getComputedStyle(element).transform);
      return Math.atan2(matrix.b, matrix.a) * 180 / Math.PI;
    });
    await expect(rotation.getByRole('img', { name: 'Rotation: 25.0 %', exact: true })).toHaveJSProperty('naturalWidth', 4);
    await expect.poll(turn).toBeCloseTo(45);
    const rotorBox = await rotor.boundingBox(), rotationBox = await rotation.locator('.motion-travel').boundingBox();
    expect(rotorBox.x + rotorBox.width / 2).toBeCloseTo(rotationBox.x + rotationBox.width / 2, 0);
    expect(rotorBox.y + rotorBox.height / 2).toBeCloseTo(rotationBox.y + rotationBox.height / 2, 0);
    expect(rotorBox.width).toBeLessThan(rotationBox.width);
    expect(rotorBox.height).toBeLessThan(rotationBox.height);
    const live = await (await page.request.get('/api/tags')).json();
    live.values.ValveOpen = false;
    live.values.FixtureState = 2;
    await page.route('**/api/tags', route => route.fulfill({ json: live }));
    const closed = control.getByRole('img', { name: 'Valve: Closed', exact: true });
    await expect(closed).toHaveAttribute('src', '/api/canvas-images/' + image.off_image);
    await expect(closed).toHaveJSProperty('naturalWidth', 4);
    await expect(multi.getByRole('img', { name: 'Fixture: Released', exact: true })).toHaveJSProperty('naturalWidth', 4);
    live.values.FixtureState = 99;
    await expect(multi).toContainText('Unknown state (99)');
    await expect(multi.locator('img')).toHaveCount(0);
    live.samples.FixtureState = { quality: 'stale', age_seconds: 4 };
    await expect(multi).toContainText('STALE DATA');
    await expect(multi).not.toContainText('Unknown state');
    live.samples.ValveOpen = { quality: 'stale', age_seconds: 4 };
    await expect(control).toContainText('STALE DATA');
    await expect(control.locator('img')).toHaveCount(0);
    live.values.AxisTravel = 0;
    live.values.ValveAngle = 0;
    await expect.poll(offset).toBeCloseTo(1);
    await expect.poll(turn).toBeCloseTo(90);
    live.values.AxisTravel = 100;
    live.values.ValveAngle = 100;
    await expect.poll(offset).toBeCloseTo(0);
    await expect.poll(turn).toBeCloseTo(-90);
    live.values.AxisTravel = 120;
    await expect(position).toContainText('120.0 mm');
    await expect(position).toContainText('OUT OF SCALE');
    await expect(marker).toHaveCount(0);
    live.samples.AxisTravel = { quality: 'stale', age_seconds: 4 };
    live.samples.ValveAngle = { quality: 'stale', age_seconds: 4 };
    await expect(rotation).toContainText('STALE DATA');
    await expect(rotor).toHaveCount(0);
    await expect(position).toContainText('STALE DATA');
    await expect(marker).toHaveCount(0);
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('project image picker reuses assets in controls and freeform layers', async ({ page }) => {
  test.setTimeout(60000);
  const original = await (await page.request.get('/api/project')).json();
  try {
    const drawing = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGPsMZVgwAaYsIoOWgkAr1IA6dkMhO8AAAAASUVORK5CYII=', 'base64');
    const uploaded = await page.request.post('/api/canvas-images?name=Equipment.png', { data: drawing });
    expect(uploaded.ok(), await uploaded.text()).toBe(true);
    const { id } = await uploaded.json();
    await save(page, { ...original.active, layout: null, screens: [],
      tags: [{ name: 'Equipment', type: 'struct', initial: { Running: false }, members: { Running: 'boolean' } }],
      faceplates: [{ id: 'equipment', name: 'Equipment', members: { Running: 'boolean' }, controls: [
        { id: 'drawing', kind: 'image', label: 'Equipment drawing', image: id, alt_text: 'Equipment outline', show_label: false },
      ] }],
      controls: [{ id: 'equipment_panel', kind: 'faceplate', label: 'Equipment panel', template: 'equipment', root_tag: 'Equipment' }],
    });
    await page.goto('/');
    const block = page.getByRole('button', { name: 'Image', exact: true });
    await block.scrollIntoViewIfNeeded();
    const source = await block.boundingBox();
    const target = await page.locator('.hmi-grid').boundingBox();
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
    await page.mouse.down();
    await page.mouse.move(target.x + 100, target.y + 30, { steps: 10 });
    await page.mouse.move(target.x + 110, target.y + 17, { steps: 2 });
    await page.mouse.up();
    const dropped = page.locator('[data-control="image"] .hmi-label').getByText('Image', { exact: true });
    await dropped.click();
    await page.getByRole('textbox', { name: 'Alternative text', exact: true }).fill('Machine schematic');
    await page.getByRole('combobox', { name: 'Image fit', exact: true }).selectOption({ label: 'Cover' });
    await page.getByRole('combobox', { name: 'Show caption', exact: true }).selectOption({ label: 'No' });
    const upload = page.getByRole('group', { name: 'Project image', exact: true });
    let uploads = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/canvas-images') uploads += 1;
    });
    await upload.getByRole('button', { name: 'Choose from project', exact: true }).click();
    const picker = page.getByRole('dialog', { name: 'Project images', exact: true });
    const search = picker.getByRole('searchbox', { name: 'Search project images', exact: true });
    const submitSearch = picker.getByRole('button', { name: 'Search', exact: true });
    const equipment = picker.getByRole('button', { name: `Use Equipment.png (${id.slice(0, 8)})`, exact: true });
    await search.fill('no-such-asset');
    await submitSearch.click();
    await expect(picker.getByText('No matching project images')).toBeVisible();
    await picker.getByRole('button', { name: 'Clear search', exact: true }).click();
    await expect(equipment).toBeVisible();
    await search.fill('EQUIP');
    await search.press('Enter');
    await expect(picker.locator('.project-image-list button')).toHaveCount(1);
    await equipment.click();
    expect(uploads).toBe(0);
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');

    await page.goto('/runtime');
    const image = page.getByRole('img', { name: 'Machine schematic', exact: true });
    await expect(image).toHaveAttribute('src', '/api/canvas-images/' + id);
    await expect(image).toHaveCSS('object-fit', 'cover');
    await expect(image).toHaveJSProperty('naturalWidth', 8);
    await expect(page.locator('[data-control="faceplate"]').getByRole('img', { name: 'Equipment outline', exact: true })).toBeVisible();
    const { active } = await (await page.request.get('/api/project')).json();
    const configured = active.controls.find(control => control.kind === 'image');
    expect(configured).toMatchObject({ image: id, fit: 'cover', show_label: false });
    expect(Object.hasOwn(configured, 'tag')).toBe(false);

    await page.goto('/');
    await page.getByRole('button', { name: 'Enable freeform layout' }).click();
    const canvas = page.getByLabel('Freeform canvas', { exact: true });
    const background = page.getByRole('button', { name: 'Choose background from project', exact: true });
    const pan = page.getByRole('button', { name: 'Pan canvas', exact: true });
    await pan.click();
    await background.click();
    await expect(picker).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(picker).toBeHidden();
    await expect(pan).toHaveAttribute('aria-pressed', 'true');
    await expect(background).toBeFocused();
    await pan.click();
    await background.click();
    await search.fill(id.slice(0, 8).toUpperCase());
    await submitSearch.click();
    await expect(picker.locator('.project-image-list button')).toHaveCount(1);
    await equipment.click();
    await expect(background).toBeFocused();
    await expect(canvas.locator('.canvas-background')).toHaveAttribute('src', '/api/canvas-images/' + id);

    await page.getByRole('button', { name: 'Choose image object from project', exact: true }).click();
    await equipment.click();
    await expect(canvas.locator('.canvas-selected .canvas-decoration-art')).toHaveAttribute('src', '/api/canvas-images/' + id);
    await page.getByRole('button', { name: 'Lock as background', exact: true }).click();
    await expect(canvas.locator('[data-background-locked] .canvas-decoration-art')).toHaveAttribute('src', '/api/canvas-images/' + id);
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    expect(uploads).toBe(0);

    await page.goto('/runtime');
    const runtime = page.getByLabel('Freeform screen', { exact: true });
    await expect(runtime.locator('.canvas-background')).toHaveAttribute('src', '/api/canvas-images/' + id);
    await expect(runtime.locator('[data-background-locked] img')).toHaveAttribute('src', '/api/canvas-images/' + id);
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('runtime fit width preserves canvas alignment, controls and trend cursor', async ({ page }) => {
  await page.setViewportSize({ width: 620, height: 780 });
  const original = await (await page.request.get('/api/project')).json();
  try {
    const uploaded = await page.request.post('/api/canvas-images', { data: pixel });
    expect(uploaded.ok(), await uploaded.text()).toBe(true);
    const image = (await uploaded.json()).id;
    await save(page, { ...original.active, screens: [], controls: [
      { id: 'trend', kind: 'trend', label: 'Station trend', tags: ['TankLevel'], seconds: 10 },
      { id: 'station_toggle', kind: 'button', label: 'Toggle fixture motor', action: 'toggle_motor' },
    ], layout: { width: 1200, height: 720, background: image, boxes: {
      trend: { x: 16, y: 20, width: 640, height: 480 },
      station_toggle: { x: 976, y: 32, width: 180, height: 86 },
    }, decorations: {
      machine: { kind: 'image', label: 'Machine', image, locked: true, x: 900, y: 20, width: 280, height: 150 },
    } } });
    await page.route(url => url.pathname === '/api/history', route => route.fulfill({ json: {
      start: 100, end: 110, truncated: false,
      samples: [{ tag: 'TankLevel', epoch: 100, value: 10, quality: 'good' },
        { tag: 'TankLevel', epoch: 110, value: 30, quality: 'good' }],
    } }));
    await page.goto('/runtime');
    const canvas = page.getByLabel('Freeform screen', { exact: true });
    const display = page.getByRole('group', { name: 'Canvas display', exact: true });
    await expect(display.getByRole('button', { name: 'Actual size', exact: true })).toHaveAttribute('aria-pressed', 'true');
    expect((await canvas.boundingBox()).width).toBe(1200);
    await display.getByRole('button', { name: 'Fit width', exact: true }).click();
    await expect(display).toContainText('52% scale');
    const area = await canvas.boundingBox();
    const background = await canvas.locator('.canvas-background').boundingBox();
    const control = await canvas.locator('[data-canvas-object="station_toggle"]').boundingBox();
    const machine = await canvas.locator('[data-background-locked]').boundingBox();
    expect(area.width).toBeLessThanOrEqual(620);
    expect(background.width).toBeCloseTo(area.width, 0);
    expect(control.x - area.x).toBeCloseTo(976 * area.width / 1200, 0);
    expect(machine.x - area.x).toBeCloseTo(900 * area.width / 1200, 0);

    const initial = (await (await page.request.get('/api/tags')).json()).values.MotorRunning;
    await canvas.getByRole('button', { name: 'Toggle fixture motor', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.MotorRunning).toBe(!initial);
    const analog = canvas.getByRole('img', { name: 'Station trend trend', exact: true });
    const bounds = await analog.boundingBox();
    await analog.hover({ position: { x: bounds.width / 2, y: bounds.height / 2 } });
    const atCursor = canvas.locator('[data-trend-value="TankLevel"] [data-trend-cursor-value]');
    await expect.poll(async () => Math.abs(Number(await atCursor.textContent()) - 20)).toBeLessThan(0.5);

    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(display).toContainText('100% scale');
    await page.setViewportSize({ width: 620, height: 780 });
    await expect(display).toContainText('52% scale');
    await display.getByRole('button', { name: 'Actual size', exact: true }).click();
    expect((await canvas.boundingBox()).width).toBe(1200);
    expect((await (await page.request.get('/api/project')).json()).active.layout.width).toBe(1200);
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('freeform layout supports backgrounds, overlap, selection and containers through apply', async ({ page, context }) => {
  test.setTimeout(120000);
  const original = await (await page.request.get('/api/project')).json();
  try {
    await save(page, { ...original.active, controls: [
      { kind: 'numeric', id: 'level', label: 'Level fixture', tag: 'TankLevel', unit: '%' },
      { kind: 'indicator', id: 'motor', label: 'Motor fixture', tag: 'MotorRunning' },
      { kind: 'text', id: 'note', label: 'Note fixture', tag: 'OperatorText' },
    ], screens: [] });
    await page.goto('/');
    await page.getByRole('button', { name: 'Enable freeform layout' }).click();
    const canvas = page.getByLabel('Freeform canvas', { exact: true });
    const outline = page.getByRole('group', { name: 'Objects', exact: true });
    const choose = (label, modifiers = []) => outline.getByRole('button', { name: label, exact: true }).click({ modifiers });
    const dimension = async (label, value) => {
      const field = page.getByRole('spinbutton', { name: label, exact: true });
      await field.fill(String(value));
      await field.press('Enter');
    };
    const level = canvas.locator('[data-canvas-object="level"]');
    const motor = canvas.locator('[data-canvas-object="motor"]');
    await choose('Level fixture');
    await dimension('X', 64);
    await dimension('Y', 64);
    await choose('Motor fixture');
    await dimension('X', 64);
    await dimension('Y', 64);
    await expect(level).toHaveCSS('left', '64px');
    await expect(motor).toHaveCSS('top', '64px');
    await page.getByRole('button', { name: 'Send to back' }).click();
    await expect(motor).toHaveCSS('z-index', '1');
    await choose('Level fixture', ['Shift']);
    await page.getByRole('button', { name: 'Group', exact: true }).click();
    const grip = level.getByRole('button', { name: 'Select and move Level fixture' });
    await grip.scrollIntoViewIfNeeded();
    const point = await grip.boundingBox();
    await page.mouse.move(point.x + 40, point.y + 30);
    await page.mouse.down();
    await page.mouse.move(point.x + 73, point.y + 30, { steps: 8 });
    await page.mouse.up();
    await expect(level).toHaveCSS('left', '96px');
    await expect(motor).toHaveCSS('left', '96px');
    await page.keyboard.press('Control+z');
    await expect(level).toHaveCSS('left', '64px');
    await expect(motor).toHaveCSS('left', '64px');
    await page.keyboard.press('Control+y');
    await expect(level).toHaveCSS('left', '96px');
    await expect(motor).toHaveCSS('left', '96px');
    await page.getByRole('button', { name: 'Ungroup', exact: true }).click();
    await choose('Motor fixture');
    await dimension('Y', 120);
    await choose('Level fixture', ['Shift']);
    await page.getByRole('button', { name: 'Align top' }).click();
    await expect(motor).toHaveCSS('top', '64px');

    await page.getByRole('button', { name: 'Pack into scrollable stack' }).click();
    const stack = canvas.locator('.canvas-container-stack');
    await expect(stack.locator('.canvas-member')).toHaveCount(2);
    await dimension('Height', 48);
    await choose('Note fixture');
    await dimension('X', 400);
    const properties = page.getByRole('group', { name: 'Control properties', exact: true });
    await properties.getByRole('textbox', { name: 'Label', exact: true }).fill('Machine note');
    const image = page.getByLabel('Background image', { exact: true });
    await image.setInputFiles({ name: 'machine.png', mimeType: 'image/png', buffer: pixel });
    await expect(canvas.locator('.canvas-background')).toBeVisible();

    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const project = (await (await page.request.get('/api/project')).json()).active;
    expect(Object.values(project.layout.containers)[0].members).toHaveLength(2);
    expect(project.layout.boxes.note.x).toBe(400);
    const viewer = await context.newPage();
    await viewer.goto('/runtime');
    const runtime = viewer.getByLabel('Freeform screen', { exact: true });
    await expect(runtime.locator('.canvas-background')).toHaveJSProperty('complete', true);
    await expect(runtime.locator('.canvas-background')).toHaveJSProperty('naturalWidth', 1);
    await expect(runtime.locator('[data-control="text"]')).toContainText('Machine note');
    await expect(runtime.locator('[data-control="numeric"]')).toContainText('42.0');
    const scroll = runtime.locator('.canvas-container-stack').locator('..');
    expect(await scroll.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);

    await page.reload();
    await expect(page.getByLabel('Freeform canvas', { exact: true }).locator('.canvas-background')).toBeVisible();
    await expect(page.locator('[data-canvas-object="note"]')).toHaveCSS('left', '400px');

    await choose('Scrollable stack');
    await page.getByRole('button', { name: 'Unpack container' }).click();
    await choose('Level fixture');
    await dimension('X', 0);
    await choose('Motor fixture');
    await dimension('X', 148);
    await choose('Level fixture', ['Shift']);
    await choose('Machine note', ['Shift']);
    await page.getByRole('button', { name: 'Space horizontally' }).click();
    await expect(motor).toHaveCSS('left', '200px');
    await page.getByRole('button', { name: 'Pack into grid' }).click();
    await dimension('Grid columns', 3);
    await expect(canvas.locator('.canvas-container-grid .canvas-member')).toHaveCount(3);

    const palette = page.getByRole('group', { name: 'Control palette' });
    await palette.getByRole('combobox', { name: 'Control type' }).selectOption('Indicator');
    const source = palette.getByRole('button', { name: 'Add or drag control' });
    await source.dragTo(canvas, { targetPosition: { x: 328, y: 248 } });
    const added = canvas.locator('.canvas-selected');
    await expect(added).toHaveCSS('left', '328px');
    await expect(added).toHaveCSS('top', '248px');
    const resize = added.getByRole('button', { name: 'Resize Motor' });
    await resize.scrollIntoViewIfNeeded();
    const handle = await resize.boundingBox();
    await page.mouse.move(handle.x + 6, handle.y + 6);
    await page.mouse.down();
    await page.mouse.move(handle.x + 35, handle.y + 6, { steps: 8 });
    await page.mouse.up();
    await expect(added).toHaveCSS('width', '208px');

    const imagesAndShapes = page.getByRole('group', { name: 'Images and shapes' });
    await imagesAndShapes.getByRole('button', { name: 'Add rectangle' }).click();
    await dimension('X', 304);
    await dimension('Y', 224);
    await imagesAndShapes.getByLabel('Image object').setInputFiles({ name: 'station.png', mimeType: 'image/png', buffer: pixel });
    await expect(outline.getByRole('button', { name: 'station.png', exact: true })).toBeVisible();
    await dimension('X', 304);
    await dimension('Y', 224);
    await choose('Rectangle', ['Shift']);
    await page.getByRole('button', { name: 'Lock as background' }).click();
    await expect(canvas.locator('[data-background-locked]')).toHaveCount(2);
    await expect(canvas.locator('[data-background-locked] button')).toHaveCount(0);
    const movable = canvas.getByRole('button', { name: 'Select and move Motor', exact: true });
    await movable.scrollIntoViewIfNeeded();
    const hit = await movable.boundingBox();
    await page.mouse.move(hit.x + 32, hit.y + 28);
    await page.mouse.down();
    await page.mouse.move(hit.x + 64, hit.y + 28, { steps: 6 });
    await page.mouse.up();
    await expect(canvas.locator('.canvas-selected')).toHaveCSS('left', '360px');
    await page.getByRole('button', { name: 'Send to back' }).click();
    await expect(canvas.locator('.canvas-selected')).toHaveCSS('z-index', '1');
    await expect(canvas.locator('.canvas-background-objects')).toHaveCSS('z-index', '0');

    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    await expect(runtime.locator('[data-background-locked]')).toHaveCount(2);
    await page.reload();
    await expect(canvas.locator('[data-background-locked]')).toHaveCount(2);
    await outline.getByRole('button', { name: 'Unlock station.png' }).click();
    await expect(canvas.getByRole('button', { name: 'Select and move station.png' })).toBeVisible();
    await expect(canvas.locator('[data-background-locked]')).toHaveCount(1);

    const undo = page.getByRole('button', { name: 'Undo', exact: true });
    const redo = page.getByRole('button', { name: 'Redo', exact: true });
    await undo.click();
    await expect(canvas.locator('[data-background-locked]')).toHaveCount(2);
    await page.keyboard.press('Control+Shift+z');
    const unlocked = canvas.getByRole('button', { name: 'Select and move station.png' });
    await expect(unlocked).toBeVisible();
    await page.getByRole('button', { name: 'Remove selected', exact: true }).click();
    await expect(unlocked).toHaveCount(0);
    await undo.click();
    await expect(unlocked).toBeVisible();
    await redo.click();
    await expect(unlocked).toHaveCount(0);
    await undo.click();
    await dimension('X', 480);
    await expect(redo).toBeDisabled();
    await expect(canvas.locator('.canvas-selected')).toHaveCSS('left', '480px');
    await undo.click();
    await expect(canvas.locator('.canvas-selected')).toHaveCSS('left', '304px');
    await expect(runtime.locator('[data-background-locked]')).toHaveCount(2);

    const sourceGrid = canvas.locator('.canvas-object').filter({ has: page.locator('.canvas-container-grid') });
    const sourceX = Number.parseInt(await sourceGrid.evaluate(element => element.style.left), 10);
    await choose('Grid container');
    await page.keyboard.press('Control+d');
    await expect(canvas.locator('.canvas-container-grid')).toHaveCount(2);
    const gridCopy = canvas.locator('.canvas-selected');
    await expect(gridCopy.locator('.canvas-member')).toHaveCount(3);
    await expect(gridCopy).toHaveCSS('left', (sourceX + 8) + 'px');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('Shift+ArrowRight');
    await expect(gridCopy).toHaveCSS('left', (sourceX + 17) + 'px');
    await expect(sourceGrid.first()).toHaveCSS('left', sourceX + 'px');
    await page.getByRole('button', { name: 'Save draft', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
    const copiedProject = (await (await page.request.get('/api/project')).json()).draft;
    const grids = Object.values(copiedProject.layout.containers);
    expect(grids).toHaveLength(2);
    expect(new Set(grids.flatMap(grid => grid.members)).size).toBe(6);
    for (const grid of grids) {
      expect(grid.members.map(id => copiedProject.controls.find(control => control.id === id).tag))
        .toEqual(['MotorRunning', 'TankLevel', 'OperatorText']);
    }
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('marquee selects overlapping objects and groups at editor zoom', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  const box = (x, y, group = '') => ({ x, y, width: 88, height: 55, z: 0, group });
  try {
    await save(page, { ...original.active, controls: ['one', 'two', 'three', 'four'].map(id => ({
      kind: 'indicator', id, label: id, tag: 'MotorRunning',
    })), layout: { width: 700, height: 480, boxes: {
      one: box(40, 40), two: box(190, 40, 'pair'), three: box(390, 200, 'pair'), four: box(40, 310),
    }, decorations: { picture: {
      ...box(0, 0), kind: 'rectangle', label: 'Locked background', locked: true, width: 680, height: 460,
    } } } });
    await page.goto('/');
    const canvas = page.getByLabel('Freeform canvas', { exact: true });
    await page.getByRole('combobox', { name: 'Zoom', exact: true }).selectOption('0.75');
    const surface = await canvas.boundingBox();
    const move = (x, y) => page.mouse.move(surface.x + x * 0.75, surface.y + y * 0.75, { steps: 5 });
    async function boxSelect(start, end, modifier, cancel = false) {
      if (modifier) await page.keyboard.down(modifier);
      await move(...start);
      await page.mouse.down();
      await move(...end);
      await expect(canvas.locator('.canvas-marquee')).toBeVisible();
      if (cancel) await page.keyboard.press('Escape');
      await page.mouse.up();
      if (modifier) await page.keyboard.up(modifier);
      await expect(canvas.locator('.canvas-marquee')).toHaveCount(0);
    }
    const selected = () => canvas.locator('.canvas-selected').evaluateAll(items =>
      items.map(item => item.dataset.canvasObject).sort());
    await boxSelect([12, 12], [220, 72]);
    expect(await selected()).toEqual(['one', 'three', 'two']);
    await boxSelect([12, 280], [105, 345], 'Shift');
    expect(await selected()).toEqual(['four', 'one', 'three', 'two']);
    await boxSelect([300, 265], [410, 235], undefined, true);
    expect(await selected()).toEqual(['four', 'one', 'three', 'two']);
    await move(12, 12);
    await page.mouse.click(surface.x + 9, surface.y + 9);
    expect(await selected()).toEqual([]);
    await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeDisabled();
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('copy and paste moves a reusable selection between freeform screens', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  const box = (x, y, width, height, z = 0) => ({ x, y, width, height, z });
  try {
    const uploaded = await page.request.post('/api/canvas-images', { data: pixel });
    expect(uploaded.ok(), await uploaded.text()).toBe(true);
    const image = (await uploaded.json()).id;
    await save(page, { ...original.active,
      controls: [
        { kind: 'indicator', id: 'motor', label: 'Motor fixture', tag: 'MotorRunning' },
        { kind: 'numeric', id: 'level', label: 'Level fixture', tag: 'TankLevel', unit: '%' },
      ],
      layout: { width: 900, height: 480, boxes: {
        motor: box(505, 185, 85, 45), level: box(605, 185, 75, 45),
      }, containers: { panel: { ...box(500, 180, 190, 105), mode: 'grid', columns: 2, members: ['motor', 'level'] } },
      decorations: { image: { ...box(700, 180, 50, 40, 1), kind: 'image', image, label: 'Station picture' } } },
      screens: [{ id: 'destination', title: 'Destination', layout: { width: 320, height: 240 }, controls: [] }],
    });
    await page.goto('/');
    const outline = page.getByRole('group', { name: 'Objects', exact: true });
    const search = outline.getByRole('searchbox', { name: 'Search objects', exact: true });
    await search.fill('  MoToR  ');
    await expect(outline.getByRole('button', { name: 'Grid container', exact: true })).toBeVisible();
    await expect(outline.getByRole('button', { name: 'Motor fixture', exact: true })).toBeVisible();
    await expect(outline.getByRole('button', { name: 'Level fixture', exact: true })).toHaveCount(0);
    await outline.getByRole('button', { name: 'Motor fixture', exact: true }).click();
    await expect(page.getByRole('group', { name: 'Control properties' })).toBeVisible();
    await search.fill('missing object');
    await expect(outline.getByRole('status')).toHaveText('No matching objects.');
    await search.press('Escape');
    await expect(search).toHaveValue('');
    await expect(outline.getByRole('button', { name: 'Motor fixture', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await outline.getByRole('button', { name: 'Grid container', exact: true }).click();
    await outline.getByRole('button', { name: 'Station picture', exact: true }).click({ modifiers: ['Shift'] });
    await page.keyboard.press('Control+c');
    await expect(page.getByText(/Copied selection/)).toBeVisible();
    await page.getByRole('button', { name: 'Screens', exact: true }).click();
    await page.getByRole('button', { name: 'Edit Destination', exact: true }).click();
    const paste = page.getByRole('button', { name: 'Paste selection', exact: true });
    await paste.focus();
    await page.keyboard.press('Control+v');
    const canvas = page.getByLabel('Freeform canvas', { exact: true });
    await expect(canvas.locator('.canvas-member')).toHaveCount(2);
    await expect(canvas.locator('.canvas-object').filter({ has: page.locator('.canvas-container-grid') })).toHaveCSS('left', '70px');
    await expect(canvas.locator('img.canvas-decoration-art')).toHaveAttribute('src', '/api/canvas-images/' + image);
    await expect(canvas.locator('.canvas-object').filter({ has: page.locator('img.canvas-decoration-art') })).toHaveCSS('left', '270px');
    await expect(canvas.locator('.canvas-selected')).toHaveCount(2);
    await page.keyboard.press('Control+z');
    await expect(canvas.locator('[data-canvas-object]')).toHaveCount(0);
    await page.keyboard.press('Control+y');
    await expect(canvas.locator('.canvas-member')).toHaveCount(2);
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const project = (await (await page.request.get('/api/project')).json()).active;
    const destination = project.screens.find(screen => screen.id === 'destination');
    expect(project.controls.map(item => item.id)).toEqual(['motor', 'level']);
    expect(destination.controls.map(item => item.tag)).toEqual(['MotorRunning', 'TankLevel']);
    expect(destination.controls.every(item => !['motor', 'level'].includes(item.id))).toBe(true);
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('match object dimensions to a selected reference without moving objects', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  try {
    await save(page, { ...original.active, controls: ['reference', 'target', 'edge'].map(id => ({
      kind: 'indicator', id, label: id, tag: 'MotorRunning',
    })), layout: { width: 500, height: 300, boxes: {
      reference: { x: 20, y: 20, width: 128, height: 80 },
      target: { x: 220, y: 80, width: 88, height: 48 },
      edge: { x: 408, y: 160, width: 80, height: 50 },
    } } });
    await page.goto('/');
    const objects = page.getByRole('group', { name: 'Objects', exact: true });
    const select = (name, modifiers = []) => objects.getByRole('button', { name, exact: true }).click({ modifiers });
    const match = name => page.getByRole('button', { name, exact: true });
    const undo = page.getByRole('button', { name: 'Undo', exact: true });
    const target = page.locator('[data-canvas-object="target"]');
    await select('target');
    await select('reference', ['Shift']);
    await page.getByRole('combobox', { name: 'Size reference' }).selectOption('reference');
    await match('Match width').click();
    await expect(target).toHaveCSS('width', '128px');
    await expect(target).toHaveCSS('height', '48px');
    await undo.click();
    await expect(target).toHaveCSS('width', '88px');
    await match('Match height').click();
    await expect(target).toHaveCSS('width', '88px');
    await expect(target).toHaveCSS('height', '80px');
    await match('Match size').click();
    await expect(target).toHaveCSS('width', '128px');
    await expect(target).toHaveCSS('height', '80px');
    await expect(target).toHaveCSS('left', '220px');
    await expect(target).toHaveCSS('top', '80px');
    await select('edge', ['Shift']);
    await expect(match('Match width')).toBeDisabled();
    await expect(match('Match size')).toBeDisabled();
    await expect(match('Match height')).toBeEnabled();
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const current = (await (await page.request.get('/api/project')).json()).active;
    expect(current.layout.boxes.target).toMatchObject({ x: 220, y: 80, width: 128, height: 80 });
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('fit canvas and fit selection adjust only the designer view', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  try {
    await save(page, { ...original.active, controls: [
      { kind: 'indicator', id: 'far', label: 'Far indicator', tag: 'MotorRunning' },
    ], layout: { width: 1800, height: 1200, boxes: {
      far: { x: 1400, y: 900, width: 140, height: 70 },
    } } });
    await page.goto('/');
    const canvas = page.getByLabel('Freeform canvas', { exact: true });
    const zoom = page.getByRole('combobox', { name: 'Zoom', exact: true });
    const fitSelection = page.getByRole('button', { name: 'Fit selection', exact: true });
    await expect(fitSelection).toBeDisabled();
    await page.getByRole('button', { name: 'Fit canvas', exact: true }).click();
    expect(Number(await zoom.inputValue())).toBeLessThan(1);
    const viewport = page.locator('.canvas-workbench > .canvas-scroll');
    expect(await viewport.evaluate(element => element.scrollWidth <= element.clientWidth
      && element.scrollHeight <= element.clientHeight)).toBe(true);

    await page.getByRole('group', { name: 'Objects', exact: true })
      .getByRole('button', { name: 'Far indicator', exact: true }).click();
    await fitSelection.click();
    await expect(zoom).toHaveValue('2');
    const object = canvas.locator('[data-canvas-object="far"]');
    const position = await object.evaluate(element => {
      const item = element.getBoundingClientRect(), scroll = element.closest('.canvas-scroll');
      const frame = scroll.getBoundingClientRect();
      return { x: item.left + item.width / 2 - frame.left - scroll.clientWidth / 2,
        y: item.top + item.height / 2 - frame.top - scroll.clientHeight / 2 };
    });
    expect(Math.abs(position.x)).toBeLessThan(2);
    expect(Math.abs(position.y)).toBeLessThan(2);

    const pan = page.getByRole('button', { name: 'Pan canvas', exact: true });
    const scrollPosition = () => viewport.evaluate(element => ({ x: element.scrollLeft, y: element.scrollTop }));
    async function dragOverObject(dx, dy, button = 'left') {
      const item = await object.boundingBox();
      const x = item.x + item.width / 2, y = item.y + item.height / 2;
      await page.mouse.move(x, y);
      await page.mouse.down({ button });
      await page.mouse.move(x + dx, y + dy, { steps: 6 });
      await page.mouse.up({ button });
    }
    const initial = await scrollPosition();
    await pan.click();
    await expect(pan).toHaveAttribute('aria-pressed', 'true');
    await dragOverObject(-80, -40);
    expect(await scrollPosition()).toEqual({ x: initial.x + 80, y: initial.y + 40 });
    await expect(object).toHaveClass(/canvas-selected/);
    await page.keyboard.press('Escape');
    await expect(pan).toHaveAttribute('aria-pressed', 'false');
    await dragOverObject(50, 20, 'middle');
    expect(await scrollPosition()).toEqual({ x: initial.x + 30, y: initial.y + 20 });
    await expect(object).toHaveClass(/canvas-selected/);
    await zoom.selectOption('1.5');
    await expect(zoom).toHaveValue('1.5');
    await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeDisabled();
    const draft = (await (await page.request.get('/api/project')).json()).draft;
    expect(draft.layout.boxes.far).toMatchObject({ x: 1400, y: 900, width: 140, height: 70 });
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});

test('step selected objects one layer at a time while preserving the background', async ({ page }) => {
  const original = await (await page.request.get('/api/project')).json();
  const ids = ['one', 'two', 'three', 'four', 'five'];
  const rectangle = { x: 40, y: 40, width: 120, height: 80 };
  try {
    await save(page, { ...original.active,
      controls: ids.map(id => ({ kind: 'indicator', id, label: id, tag: 'MotorRunning' })),
      layout: { boxes: Object.fromEntries(ids.map((id, z) => [id, { ...rectangle, z }])),
        decorations: { machine: { ...rectangle, kind: 'rectangle', label: 'Machine', locked: true, z: 9999 } } },
    });
    await page.goto('/');
    const canvas = page.getByLabel('Freeform canvas', { exact: true });
    const outline = page.getByRole('group', { name: 'Objects', exact: true });
    const select = (name, modifiers = []) => outline.getByRole('button', { name, exact: true }).click({ modifiers });
    const layers = () => canvas.locator('[data-canvas-object]:not([data-background-locked])')
      .evaluateAll(items => items.map(item => item.dataset.canvasObject));
    const forward = page.getByRole('button', { name: 'Bring forward', exact: true });
    const backward = page.getByRole('button', { name: 'Send backward', exact: true });

    const search = outline.getByRole('searchbox', { name: 'Search objects', exact: true });
    await search.fill('machine');
    await expect(outline.getByRole('button', { name: 'Unlock Machine', exact: true })).toBeVisible();
    await expect(outline.getByRole('button', { name: 'one', exact: true })).toHaveCount(0);
    await search.press('Escape');
    await select('one');
    await expect(backward).toBeDisabled();
    await select('two', ['Shift']);
    await select('four', ['Shift']);
    await forward.click();
    expect(await layers()).toEqual(['three', 'one', 'two', 'five', 'four']);
    await forward.click();
    expect(await layers()).toEqual(['three', 'five', 'one', 'two', 'four']);
    await expect(forward).toBeDisabled();
    await page.getByRole('button', { name: 'Undo', exact: true }).click();
    expect(await layers()).toEqual(['three', 'one', 'two', 'five', 'four']);
    await backward.click();
    expect(await layers()).toEqual(ids);
    await forward.click();
    await expect(canvas.locator('.canvas-background-objects')).toHaveCSS('z-index', '0');
    await expect(canvas.locator('[data-background-locked]')).toHaveCSS('z-index', '10000');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
    const layout = (await (await page.request.get('/api/project')).json()).active.layout;
    expect(layout.boxes.three.z).toBe(0);
    expect(layout.boxes.four.z).toBe(4);
    expect(layout.decorations.machine).toMatchObject({ locked: true, z: 9999 });
  } finally {
    await save(page, original.active);
    await save(page, original.draft, false);
  }
});
