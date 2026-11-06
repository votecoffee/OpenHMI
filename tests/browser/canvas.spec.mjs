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

test('compact static labels and symbols survive canvas save and live apply', async ({ page }) => {
  test.setTimeout(60000);
  const original = await (await page.request.get('/api/project')).json();
  try {
    await save(page, { ...original.active, controls: [], screens: [], layout: null,
      tags: [{ name: 'Highlight', type: 'boolean', initial: true }] });
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
    expect(active.controls.map(control => control.kind)).toEqual(['label', 'symbol']);
    expect(active.controls.every(control => !Object.hasOwn(control, 'tag'))).toBe(true);
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
