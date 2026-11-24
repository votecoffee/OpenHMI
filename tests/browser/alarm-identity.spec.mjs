import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8766' });

test('alarm console rejects foreign and missing sources while retaining guidance and drafts without replay', async ({ page }) => {
  test.setTimeout(90000);
  const errors = [], mutations = [];
  page.on('pageerror', error => errors.push(error.message));
  const login = await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
  expect(login.ok()).toBe(true);
  const original = await (await page.request.get('/api/project')).json();
  async function install(project) {
    const state = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project } });
    expect(saved.ok()).toBe(true);
    expect((await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } })).ok()).toBe(true);
  }
  const project = structuredClone(original.active);
  project.controls.push({ id: 'identity_alarm', kind: 'button', label: 'Synthetic alarm toggle', action: 'toggle_alarm' });
  project.alarms = [{ ...project.alarms[0], id: 'identity_alarm', message: 'Original source alarm',
    response: '1. Inspect original sensor\n2. Restore original condition', priority: 1 }];
  let raised = false;
  try {
    await install(project);
    expect((await page.request.post('/api/controls/identity_alarm/activate', { data: {} })).ok()).toBe(true);
    raised = true;
    const rows = await (await page.request.get('/api/alarms/occurrences')).json();
    const id = rows.items[0].occurrence_id;
    expect((await page.request.post(`/api/alarms/occurrences/${id}/notes`, { data: { comment: 'Original recorded note' } })).ok()).toBe(true);
    expect((await page.request.post(`/api/alarms/occurrences/${id}/shelve`, { data: { duration_seconds: 900, reason: 'Original investigation' } })).ok()).toBe(true);
    await page.goto(`/alarms?occurrence=${id}&shelving=shelved`);
    const console = page.getByRole('region', { name: 'Alarm console', exact: true });
    const detail = page.getByRole('region', { name: 'Alarm details', exact: true });
    const shelves = page.getByRole('region', { name: 'Alarm shelving', exact: true });
    const occurrences = page.locator('.alarm-occurrences tbody');
    const events = page.locator('.alarm-events tbody');
    await expect(occurrences).toContainText('Original source alarm');
    await expect(events).toContainText('Original source alarm');
    await expect(detail).toContainText('Original recorded note');
    await expect(shelves).toContainText('Original investigation');
    await page.getByLabel('Alarm search', { exact: true }).fill('Retained unapplied search');
    await page.getByLabel('Acknowledgement comment', { exact: true }).fill('Retained acknowledgement draft');
    await detail.getByLabel('Operator note', { exact: true }).fill('Retained operator note draft');
    await page.getByLabel('Reason for shelving or restoring', { exact: true }).fill('Retained reason');
    await page.getByRole('button', { name: 'Select unacknowledged on this page', exact: true }).click();
    const ack = page.getByRole('button', { name: 'Acknowledge selected', exact: true });
    const restore = shelves.getByRole('button', { name: 'Restore Original source alarm', exact: true });
    await expect(ack).toBeEnabled();
    await expect(restore).toBeEnabled();
    page.on('request', request => {
      if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/alarms/')) mutations.push(request.url());
    });
    let mode = 'history';
    const target = /^\/api\/alarms\/(occurrences(?:\/[1-9]\d*(?:\/notes)?)?|events|shelves)$/;
    await page.route('**/api/alarms/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (!target.test(path) || route.request().method() !== 'GET' || mode === 'same'
          || (mode === 'history' && path !== '/api/alarms/events')) return route.continue();
      if (mode === 'denied') return route.fulfill({ status: 403, contentType: 'text/plain', body: 'Forbidden' });
      const response = await route.fetch();
      const body = (await response.text()).replaceAll('Original', 'FOREIGN');
      const headers = { ...response.headers() };
      delete headers['content-length'];
      if (mode === 'missing') delete headers['x-openhmi-project'];
      else headers['x-openhmi-project'] = 'f'.repeat(32);
      return route.fulfill({ response, headers, body });
    });
    const historyWarning = console.getByRole('alert').filter({ hasText: 'Alarm event history unavailable' });
    await expect(historyWarning).toContainText('Showing the last page received');
    await expect(ack).toBeEnabled(); // A history fault alone cannot block a healthy occurrence page.
    await expect(detail.getByLabel('Operator note', { exact: true })).toBeEnabled();
    for (const failure of ['foreign', 'missing']) {
      mode = failure;
      await expect(console.getByRole('alert').filter({ hasText: 'Alarm occurrences unavailable' })).toBeVisible();
      await expect(detail.getByRole('alert').filter({ hasText: 'Alarm details unavailable' })).toBeVisible();
      await expect(detail.getByRole('alert').filter({ hasText: 'Operator notes unavailable' })).toBeVisible();
      await expect(shelves.getByRole('alert')).toContainText('Showing the last page received');
      await expect(ack).toBeDisabled();
      await expect(restore).toBeDisabled();
      await expect(detail.getByLabel('Operator note', { exact: true })).toBeDisabled();
      await expect(detail).toContainText('1. Inspect original sensor');
      await expect(detail).toContainText('Original recorded note');
      await expect(occurrences).toContainText('Original source alarm');
      await expect(events).toContainText('Original source alarm');
      await expect(shelves).toContainText('Original investigation');
      await expect(console).not.toContainText('FOREIGN');
      mode = 'same';
      await expect(console.getByRole('alert')).toHaveCount(0);
      await expect(ack).toBeEnabled();
      await expect(restore).toBeEnabled();
    }
    await expect(page.getByLabel('Alarm search', { exact: true })).toHaveValue('Retained unapplied search');
    await expect(page.getByLabel('Acknowledgement comment', { exact: true })).toHaveValue('Retained acknowledgement draft');
    await expect(detail.getByLabel('Operator note', { exact: true })).toHaveValue('Retained operator note draft');
    await expect(page.getByLabel('Reason for shelving or restoring', { exact: true })).toHaveValue('Retained reason');
    expect(mutations).toEqual([]);
    mode = 'denied';
    await expect(occurrences.locator('tr')).toHaveCount(0);
    await expect(events.locator('tr')).toHaveCount(0);
    await expect(detail).not.toContainText('Original recorded note');
    await expect(detail).not.toContainText('Inspect original sensor');
    await expect(shelves.locator('tbody tr')).toHaveCount(0);
    mode = 'same';
    await expect(console.getByRole('alert')).toHaveCount(0);
    await expect(detail.getByLabel('Operator note', { exact: true })).toHaveValue('Retained operator note draft');
    await expect(ack).toBeDisabled(); // Permission denial discarded rows and therefore their selection.
    await page.getByRole('button', { name: 'Select unacknowledged on this page', exact: true }).click();
    await ack.click();
    await expect(page.getByRole('status', { name: 'Alarm operation' })).toContainText('1 alarms acknowledged');
    expect(mutations).toHaveLength(1); // Only the explicit operator action dispatches.
    expect(errors).toEqual([]);
  } finally {
    await page.unroute('**/api/alarms/**');
    if (raised) await page.request.post('/api/controls/identity_alarm/activate', { data: {} });
    const pending = (await (await page.request.get('/api/alarms/occurrences?state=all&search=identity_alarm')).json()).items;
    if (pending.length) await page.request.post('/api/alarms/acknowledge-selected', { data: { occurrence_ids: pending.map(item => item.occurrence_id) } });
    await page.request.post('/api/alarms/shelves/identity_alarm/restore', { data: { expected_operation_id:
      (await (await page.request.get('/api/alarms/shelves')).json()).items.find(item => item.alarm_id === 'identity_alarm')?.operation_id, reason: 'Fixture cleanup' } });
    await install(original.active);
    const state = await (await page.request.get('/api/project')).json();
    await page.request.put('/api/project/draft', { data: { expected_revision: state.draft_revision, project: original.draft } });
  }
});
