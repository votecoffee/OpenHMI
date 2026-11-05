import { test, expect } from '@playwright/test';

const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jX1sAAAAASUVORK5CYII=', 'base64');

test('freeform layout supports backgrounds, overlap, selection and containers through apply', async ({ page, context }) => {
  test.setTimeout(90000);
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const state = await (await page.request.get('/api/project')).json();
    const response = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
    expect(response.ok(), await response.text()).toBe(true);
    if (apply) {
      const result = await page.request.post('/api/project/apply', { data: { expected_revision: (await response.json()).draft_revision } });
      expect(result.ok(), await result.text()).toBe(true);
    }
  }
  try {
    await save({ ...original.active, controls: [
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
  } finally {
    await save(original.active);
    await save(original.draft, false);
  }
});
