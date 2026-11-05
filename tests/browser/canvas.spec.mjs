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
