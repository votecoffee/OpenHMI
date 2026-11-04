import { test, expect } from '@playwright/test';

test.use({ actionTimeout: 15000 });

test('no-code command contract, accepted/completed feedback, history and timeout', async ({ page }) => {
  test.setTimeout(120000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const original = (await (await page.request.get('/api/project')).json()).draft;
  async function apply(project) {
    const revision = (await (await page.request.get('/api/project')).json()).draft_revision;
    const saved = await page.request.put('/api/project/draft', { data: { expected_revision: revision, project } });
    expect(saved.ok(), await saved.text()).toBe(true);
    const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } });
    expect(applied.ok(), await applied.text()).toBe(true);
  }
  const project = structuredClone(original);
  project.tags.push({ name: 'CycleCommand', type: 'struct', writable: true, initial: { RequestSequence: 0, AcceptedSequence: 0, CompletedSequence: 0, ResultCode: 0, Permit: true },
    members: { RequestSequence: 'integer', AcceptedSequence: 'integer', CompletedSequence: 'integer', ResultCode: 'integer', Permit: 'boolean' } });
  project.controls.push(...[['accept', 'command_accept', 'Simulate acceptance'], ['complete', 'command_complete', 'Simulate completion']].map(([id, action, label]) => ({ id: `demo_${id}`, kind: 'button', label, action })));
  await apply(project);
  await page.goto('/');
  await page.getByRole('button', { name: 'Commands', exact: true }).click();
  await page.getByLabel('Command ID', { exact: true }).fill('cycle_demo');
  await page.getByLabel('Command name', { exact: true }).fill('Demo cycle');
  await page.getByLabel('New command UDT', { exact: true }).selectOption('CycleCommand');
  await page.getByRole('button', { name: 'Add command', exact: true }).click();
  await page.getByLabel('cycle_demo permit_member', { exact: true }).selectOption('Permit');
  await page.getByLabel('Completion timeout (s)', { exact: true }).fill('15');
  await page.getByRole('button', { name: 'Screen', exact: true }).click();
  const source = await page.getByRole('button', { name: 'Action button', exact: true }).boundingBox();
  const target = await page.locator('.hmi-grid').boundingBox();
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
  await page.mouse.down(); await page.mouse.move(target.x + 100, target.y + 90, { steps: 10 });
  await page.mouse.move(target.x + 110, target.y + 100, { steps: 2 }); await page.mouse.up();
  await page.locator('[data-control="button"]').filter({ hasText: 'Toggle simulated motor' }).last().click();
  await page.getByRole('textbox', { name: 'Label', exact: true }).fill('Request demo cycle');
  await page.getByRole('combobox', { name: 'Action type', exact: true }).selectOption({ label: 'PLC command transaction' });
  await page.getByRole('combobox', { name: 'PLC command contract', exact: true }).selectOption({ label: 'Demo cycle' });
  await page.getByRole('button', { name: 'Apply live', exact: true }).click();
  await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');
  await page.goto('/runtime');
  const request = page.getByRole('button', { name: 'Request demo cycle', exact: true });
  await request.click();
  const command = page.locator('[data-control="button"]').filter({ has: request });
  await expect(command).toContainText('PLC command: requested');
  await expect(request).toBeDisabled();
  await page.getByRole('button', { name: 'Simulate acceptance', exact: true }).click();
  await expect(command).toContainText('PLC command: accepted');
  await expect(command).not.toContainText('PLC command: completed');
  await page.getByRole('button', { name: 'Simulate completion', exact: true }).click();
  await expect(command).toContainText('PLC command: completed');
  await expect(request).toBeEnabled();
  await page.getByRole('link', { name: 'Commands', exact: true }).click();
  await expect(page.getByRole('region', { name: 'PLC command transactions', exact: true })).toBeVisible();
  const row = page.locator('.activity-table tbody tr').first();
  await expect(row).toContainText('completed');
  await row.getByText('Transaction details', { exact: true }).click();
  await expect(row).toContainText('PLC accepted this sequence');
  await row.getByRole('link', { name: 'Operator activity', exact: true }).click();
  await expect(page.locator('.activity-table tbody tr')).toHaveCount(1);
  await page.locator('.activity-table tbody tr').getByText('Operation details', { exact: true }).click();
  await expect(page.locator('.activity-table tbody tr')).toContainText('request_tag_readback');
  // Use a short timeout on a second request, then reconcile through PLC-owned feedback.
  const short = (await (await page.request.get('/api/project')).json()).draft;
  short.commands.find(item => item.id === 'cycle_demo').timeout_seconds = 1;
  await apply(short);
  await page.goto('/runtime');
  await page.getByRole('button', { name: 'Request demo cycle', exact: true }).click();
  await expect(page.getByText(/PLC command: uncertain/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Request demo cycle', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Simulate completion', exact: true }).click();
  await expect(page.getByText(/PLC command: completed/)).toBeVisible();
  expect((await (await page.request.get('/api/tags')).json()).values['CycleCommand.RequestSequence']).toBe(2);
  if (process.env.OPENHMI_COMMAND_SCREENSHOT) { await page.goto('/commands'); await expect(page.locator('.activity-table tbody tr')).toHaveCount(2); await page.screenshot({ path: process.env.OPENHMI_COMMAND_SCREENSHOT, fullPage: true }); }
  expect(errors).toEqual([]);
  await apply(original);
});
