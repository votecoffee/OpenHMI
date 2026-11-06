import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8766' });

test('filtered acknowledgement and attributed notes preserve hidden outstanding alarms', async ({ page }) => {
  test.setTimeout(90000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/runtime');
  await page.getByRole('button', { name: 'Open HMI login', exact: true }).first().click();
  await page.getByLabel('HMI user', { exact: true }).fill('admin');
  await page.getByLabel('HMI password', { exact: true }).fill('SecurityTestOnly-2026!');
  await page.getByRole('button', { name: 'Sign in to HMI', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign out of HMI', exact: true })).toBeVisible();
  const original = await (await page.request.get('/api/project')).json();
  async function install(project) {
    const state = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
    expect(saved.ok()).toBe(true);
    const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } });
    expect(applied.ok()).toBe(true);
  }
  const project = structuredClone(original.active);
  project.controls.push({ id: 'alarm_fixture', kind: 'button', label: 'Toggle test alarm', action: 'toggle_alarm' });
  project.alarms = [
    { ...project.alarms[0], id: 'workflow_primary', message: 'Supply fault', priority: 1, cause: 'Supply pressure low', response: 'Inspect pressure regulator', related_screen: 'overview' },
    { ...project.alarms[0], id: 'workflow_secondary', message: 'Secondary fault', priority: 3 },
  ];
  let raised = false;
  try {
    await install(project);
    await page.request.post('/api/controls/alarm_fixture/activate', { data: {} });
    raised = true;
    await page.reload();
    await page.getByLabel('Screen alarm status').getByRole('link', { name: 'Alarm details: P1 Supply fault' }).press('Enter');
    const detail = page.getByRole('region', { name: 'Alarm details', exact: true });
    await expect(detail.getByRole('heading', { name: /^Alarm details #/ })).toBeFocused();
    await expect(detail.getByText('Inspect pressure regulator', { exact: true })).toBeVisible();
    await expect(page.getByText('2 active / 2 unacknowledged', { exact: true })).toBeVisible();
    const alarmStatus = await (await page.request.get('/api/alarms')).json();
    let status = { ...alarmStatus, evaluation_stale: true };
    await page.route('**/api/alarms', route => route.fulfill({ json: status }));
    const lastRecorded = page.getByText('Last recorded: 2 active / 2 unacknowledged', { exact: true });
    await expect(lastRecorded).toBeVisible();
    const ackAll = page.getByRole('button', { name: 'Acknowledge all', exact: true });
    await expect(ackAll).toBeDisabled();
    status = { ...alarmStatus, unacknowledged_count: 'invalid' };
    await expect(page.getByRole('alert')).toHaveText('ALARM MONITOR UNAVAILABLE');
    await expect(lastRecorded).toBeVisible();
    await expect(ackAll).toBeDisabled();
    await page.unroute('**/api/alarms');
    await expect(ackAll).toBeEnabled();
    await page.route('**/api/alarms/occurrences/*', async route => {
      const response = await route.fetch();
      const state = await response.json();
      state.trigger = { quality: 'bad', quality_reason: 'disconnected', age_seconds: 4.5,
        timestamp: '2026-01-01T12:00:00Z', error: 'Synthetic trigger route loss' };
      await route.fulfill({ response, json: state });
    });
    const triggerBadge = detail.getByRole('button', { name: 'Inspect ProcessAlarm quality (PLC COMM LOSS)', exact: true });
    await triggerBadge.press('Enter');
    const trigger = page.getByRole('dialog', { name: 'Tag quality details', exact: true });
    await expect(trigger).toContainText('Synthetic trigger route loss');
    await expect(trigger).toContainText('4.5 s old');
    await page.keyboard.press('Escape');
    await expect(triggerBadge).toBeFocused();
    await expect(page.getByText('2 active / 2 unacknowledged', { exact: true })).toBeVisible();
    await page.unroute('**/api/alarms/occurrences/*');
    await expect(detail.getByText(/Current trigger quality: Good data/)).toBeVisible();
    await page.getByLabel('Priority', { exact: true }).selectOption('1');
    await page.getByRole('button', { name: 'Apply alarm filters', exact: true }).click();
    await expect(page.locator('.alarm-occurrences tbody tr')).toHaveCount(1);
    const occurrences = page.locator('.alarm-occurrences tbody');
    const events = page.locator('.alarm-events tbody');
    await expect(events).toContainText('Supply fault');
    await page.route('**/api/alarms/occurrences?*', route => route.fulfill({ json: { items: [null] } }));
    const occurrencesWarning = page.getByRole('alert').filter({ hasText: 'Alarm occurrences unavailable' });
    await expect(occurrencesWarning).toContainText('Showing the last page received');
    await expect(occurrences).toContainText('Supply fault');
    await expect(events).toContainText('Supply fault');
    await expect(ackAll).toBeDisabled();
    await page.unroute('**/api/alarms/occurrences?*');
    await expect(occurrencesWarning).toBeHidden();

    await page.route('**/api/alarms/events?*', route => route.fulfill({ json: { items: [null] } }));
    const historyWarning = page.getByRole('alert').filter({ hasText: 'Alarm event history unavailable' });
    await expect(historyWarning).toContainText('Showing the last page received');
    await expect(events).toContainText('Supply fault');
    await expect(ackAll).toBeEnabled();
    await page.getByLabel('Acknowledgement comment', { exact: true }).fill('Inspecting supply');
    await page.getByRole('button', { name: 'Select unacknowledged on this page', exact: true }).click();
    await page.getByRole('button', { name: 'Acknowledge selected', exact: true }).click();
    await expect(page.getByText('2 active / 1 unacknowledged', { exact: true })).toBeVisible();
    await expect(occurrences).toContainText('Acknowledged by: admin');
    await page.unroute('**/api/alarms/events?*');
    await expect(historyWarning).toBeHidden();
    const primary = (await (await page.request.get('/api/alarms/occurrences?search=workflow_primary')).json()).items[0];
    await page.getByRole('button', { name: `Details ${primary.occurrence_id}`, exact: true }).click();
    await expect(detail.getByText('Supply pressure low', { exact: true })).toBeVisible();
    await expect(detail.getByText('Inspect pressure regulator', { exact: true })).toBeVisible();
    await expect(detail.getByRole('link')).toHaveAttribute('href', '/runtime?screen=overview');
    await detail.getByLabel('Operator note', { exact: true }).fill('Regulator inspected; awaiting supply');
    await detail.getByRole('button', { name: 'Save operator note', exact: true }).click();
    await expect(detail.getByRole('cell', { name: 'Regulator inspected; awaiting supply', exact: true })).toBeVisible();
    await expect(detail.getByRole('cell').filter({ hasText: 'admin (local)' })).toBeVisible();
    await page.getByLabel('Event filter', { exact: true }).selectOption('operator_note');
    const download = page.waitForEvent('download');
    await page.getByRole('link', { name: 'Export alarm events CSV', exact: true }).click();
    expect((await download).suggestedFilename()).toBe('alarm-events.csv');
    await page.getByLabel('Reason for shelving or restoring', { exact: true }).fill('Supply investigation');
    await detail.getByRole('button', { name: 'Shelve this alarm', exact: true }).click();
    await expect(page.locator('.alarm-occurrences tbody tr')).toHaveCount(0);
    await expect(page.getByText('2 active / 1 unacknowledged', { exact: true })).toBeVisible();
    const shelves = page.getByRole('region', { name: 'Alarm shelving', exact: true });
    await expect(shelves.getByRole('cell', { name: 'Supply investigation', exact: true })).toBeVisible();
    if (process.env.OPENHMI_SHELVING_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_SHELVING_SCREENSHOT, fullPage: true });
    const viewer = await page.context().newPage();
    await viewer.goto('/runtime');
    await expect(viewer.getByLabel('Screen alarm status')).toContainText('P3 Secondary fault');
    await expect(viewer.getByRole('link', { name: 'Alarm details: P3 Secondary fault' })).toBeVisible();
    await viewer.getByRole('link', { name: 'Shelved alarm definitions: 1', exact: true }).click();
    await expect(viewer.getByLabel('Shelving filter', { exact: true })).toHaveValue('shelved');
    await expect(viewer.locator('.alarm-occurrences tbody tr')).toHaveCount(1);
    await viewer.close();
    await page.getByLabel('Reason for shelving or restoring', { exact: true }).fill('Supply reviewed');
    await shelves.getByRole('button', { name: 'Restore Supply fault', exact: true }).click();
    await expect(page.locator('.alarm-occurrences tbody tr')).toHaveCount(1);
    if (process.env.OPENHMI_ALARM_WORKFLOWS_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_ALARM_WORKFLOWS_SCREENSHOT, fullPage: true });
    await page.getByRole('button', { name: 'Sign out of HMI', exact: true }).click();
    await expect(detail.getByLabel('Operator note', { exact: true })).toBeDisabled();
    expect(errors).toEqual([]);
  } finally {
    // Restore the synthetic shared server without leaving pending test alarms.
    await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
    if (raised) await page.request.post('/api/controls/alarm_fixture/activate', { data: {} });
    const pending = (await (await page.request.get('/api/alarms/occurrences?state=all&search=workflow_')).json()).items;
    if (pending.length) await page.request.post('/api/alarms/acknowledge-selected', { data: { occurrence_ids: pending.map(item => item.occurrence_id) } });
    await install(original.active);
    const state = await (await page.request.get('/api/project')).json();
    await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project: original.draft } });
  }
});
