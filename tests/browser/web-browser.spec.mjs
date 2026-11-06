import { once } from 'node:events';
import { createServer } from 'node:http';
import { test, expect } from '@playwright/test';

test.use({
  actionTimeout: 8000,
  launchOptions: { args: ['--host-resolver-rules=MAP *.localhost 127.0.0.1', '--no-proxy-server'] },
});

test('configure a camera and exercise approved navigation, isolation and refresh in the runtime', async ({ page, context }) => {
  test.setTimeout(90000);
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const state = await (await page.request.get('/api/project')).json();
    const draft = await page.request.put('/api/project/draft', { data: { project, expected_revision: state.draft_revision } });
    expect(draft.ok(), await draft.text()).toBe(true);
    if (apply) {
      const response = await page.request.post('/api/project/apply', { data: { expected_revision: (await draft.json()).draft_revision } });
      expect(response.ok(), await response.text()).toBe(true);
    }
  }
  const tags = [
    { name: 'CameraAddress', type: 'string', initial: 'camera-a.localhost' },
    { name: 'CameraRefresh', type: 'boolean', initial: false },
    { name: 'CameraSequence', type: 'integer', initial: 10 },
  ];
  const hits = {};
  let redirect = false;
  let stalled = false;
  const headers = {};
  const server = createServer((request, response) => {
    const host = request.headers.host.split(':')[0], key = host + request.url;
    hits[key] = (hits[key] || 0) + 1;
    headers[key] = request.headers;
    response.setHeader('cache-control', 'no-store');
    if (stalled && key === 'camera-b.localhost/view') return;
    if (redirect && key === 'camera-b.localhost/view') {
      response.writeHead(302, { location: 'http://camera-outside.localhost:' + port + '/view' }).end();
      return;
    }
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }).end('<h1>' + key + '</h1>');
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address();
  const endpoint = host => 'http://' + host + ':' + port + '/view';

  try {
    await save({ ...original.active, layout: null, columns: 1, update_ms: 100, tags });
    await page.goto('/');
    const block = page.getByRole('button', { name: 'Web Browser / Camera View', exact: true });
    await block.scrollIntoViewIfNeeded();
    const source = await block.boundingBox();
    const target = await page.locator('.hmi-grid').boundingBox();
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
    await page.mouse.down();
    await page.mouse.move(target.x + target.width / 2, target.y + 30, { steps: 12 });
    await page.mouse.move(target.x + target.width / 2, target.y + 17, { steps: 3 });
    await page.mouse.up();
    const preview = page.locator('[data-control="web_browser"]');
    await expect(preview).toHaveCount(1);
    await expect(preview.locator('iframe')).toHaveCount(0);
    await preview.locator('.hmi-label').click();
    await page.getByRole('combobox', { name: 'Scheme', exact: true }).selectOption({ label: 'HTTP' });
    await page.getByRole('spinbutton', { name: 'Port (blank uses scheme default)', exact: true }).fill(String(port));
    await page.getByRole('textbox', { name: 'Approved hosts (comma-separated)', exact: true }).fill('camera-a.localhost');
    await page.getByRole('textbox', { name: 'Approved path', exact: true }).fill('/fixed');
    await page.getByRole('combobox', { name: 'Refresh from tag', exact: true }).selectOption('CameraSequence');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');

    const active = (await (await page.request.get('/api/project')).json()).active;
    const fixedControl = active.controls.find(control => control.kind === 'web_browser');
    expect(fixedControl).toMatchObject({ hosts: 'camera-a.localhost', path: '/fixed', refresh_tag: 'CameraSequence' });
    const boundControl = {
      ...fixedControl, id: 'bound-camera', label: 'PLC camera', hosts: 'camera-a.localhost, camera-b.localhost',
      path: '/view', address_tag: 'CameraAddress', refresh_tag: 'CameraRefresh',
    };
    await save({ ...active, controls: [fixedControl, boundControl] });

    await context.addCookies([{ name: 'existing_camera_session', value: 'fixture', url: endpoint('camera-a.localhost') }]);
    let values = { CameraAddress: 'camera-a.localhost', CameraRefresh: false, CameraSequence: 10 };
    let samples = {};
    let refreshPulse = false;
    await page.route('**/api/tags', async route => {
      await route.fulfill({ json: { values, samples } });
      if (refreshPulse) {
        refreshPulse = false;
        samples = { CameraRefresh: { quality: 'stale', age_seconds: 3 } };
      }
    });
    await page.goto('/runtime');
    const fixed = page.locator('[data-control="web_browser"]').filter({ hasText: 'Camera view' });
    const bound = page.locator('[data-control="web_browser"]').filter({ hasText: 'PLC camera' });
    const cameraHeading = (control, heading) => control.frameLocator('iframe.camera-frame').frameLocator('iframe')
      .getByRole('heading', { name: heading, exact: true });
    await expect(cameraHeading(fixed, 'camera-a.localhost/fixed')).toBeVisible();
    await expect(cameraHeading(bound, 'camera-a.localhost/view')).toBeVisible();
    await expect(bound.locator('iframe.camera-frame')).toHaveAttribute('sandbox', 'allow-scripts');
    await expect(bound.frameLocator('iframe.camera-frame').locator('iframe')).toHaveAttribute('credentialless', '');
    await expect(bound).toContainText('Camera health unverified');
    expect(await cameraHeading(bound, 'camera-a.localhost/view').evaluate(() => ({
      origin: window.origin, isolated: window.credentialless,
    }))).toEqual({ origin: 'null', isolated: true });
    expect(headers['camera-a.localhost/view'].cookie).toBeUndefined();
    expect(headers['camera-a.localhost/view'].referer).toBeUndefined();

    values = { ...values, CameraRefresh: true, CameraSequence: 11 };
    await expect.poll(() => hits['camera-a.localhost/view']).toBe(2);
    await expect.poll(() => hits['camera-a.localhost/fixed']).toBe(2);
    await page.waitForTimeout(1100);
    expect(hits['camera-a.localhost/view']).toBe(2);
    expect(hits['camera-a.localhost/fixed']).toBe(2);
    values = { ...values, CameraRefresh: false };
    await page.waitForResponse('**/api/tags');
    const manualRefresh = bound.getByRole('button', { name: 'Refresh camera', exact: true });
    await manualRefresh.click();
    await expect.poll(() => hits['camera-a.localhost/view']).toBe(3);
    values = { ...values, CameraRefresh: true };
    refreshPulse = true;
    await expect(bound).toContainText('STALE DATA');
    await page.waitForTimeout(1100);
    expect(hits['camera-a.localhost/view']).toBe(3);
    await manualRefresh.click();
    await expect.poll(() => hits['camera-a.localhost/view']).toBe(4);
    samples = {};
    await expect(bound).not.toContainText('STALE DATA');
    await page.waitForTimeout(1100);
    expect(hits['camera-a.localhost/view']).toBe(4);

    samples = { CameraAddress: { quality: 'stale', age_seconds: 3 } };
    await expect(bound).toContainText('STALE DATA');
    await expect(bound.locator('iframe')).toHaveCount(0);
    samples = {};
    values = { ...values, CameraAddress: endpoint('camera-b.localhost') };
    await expect.poll(() => hits['camera-b.localhost/view'], { timeout: 15000 }).toBe(1);
    await expect(cameraHeading(bound, 'camera-b.localhost/view')).toBeVisible({ timeout: 15000 });
    const popup = context.waitForEvent('page', { timeout: 8000 });
    await bound.getByRole('button', { name: 'Open camera in new tab', exact: true }).click();
    const tab = await popup;
    await expect(tab).toHaveURL(endpoint('camera-b.localhost'));
    expect(await tab.evaluate(() => window.opener === null)).toBe(true);
    await tab.close();

    stalled = true;
    const beforeStall = hits['camera-b.localhost/view'];
    await manualRefresh.click();
    await expect.poll(() => hits['camera-b.localhost/view']).toBe(beforeStall + 1);
    const cameraStatus = bound.getByRole('status');
    await expect(cameraStatus).toContainText('Opening embedded page');
    await expect(cameraStatus).toContainText('Camera page is taking too long to open', { timeout: 13000 });
    await expect(cameraHeading(fixed, 'camera-a.localhost/fixed')).toBeVisible();
    await expect(bound.getByRole('button', { name: 'Open camera in new tab' })).toBeEnabled();
    expect(hits['camera-b.localhost/view']).toBe(beforeStall + 1);
    stalled = false;
    await manualRefresh.click();
    await expect(cameraHeading(bound, 'camera-b.localhost/view')).toBeVisible();
    await expect(cameraStatus).toContainText('Camera health unverified');

    redirect = true;
    const before = hits['camera-b.localhost/view'];
    await bound.getByRole('button', { name: 'Refresh camera', exact: true }).click();
    await expect.poll(() => hits['camera-b.localhost/view']).toBe(before + 1);
    await expect(bound).toContainText('Camera health unverified');
    expect(hits['camera-outside.localhost/view']).toBeUndefined();

    for (const address of ['javascript:alert(1)', endpoint('user@camera-a.localhost'),
      endpoint('camera-a.localhost') + '/../view', 'http://camera-a.localhost:443/view', 'camera-outside.localhost']) {
      values = { ...values, CameraAddress: address };
      await expect(bound).toContainText('CAMERA ADDRESS MISSING OR BLOCKED');
      await expect(bound.locator('iframe')).toHaveCount(0);
    }
    redirect = false;
    values = { ...values, CameraAddress: 123 };
    await expect(bound).toContainText('BAD DATA');
    await expect(bound.locator('iframe')).toHaveCount(0);
    values = { ...values, CameraAddress: 'camera-a.localhost' };
    await expect(cameraHeading(bound, 'camera-a.localhost/view')).toBeVisible();
    const displayed = await (await page.request.get('/api/project/active')).json();
    await page.route('**/api/project/active', route => route.fulfill({ json: {
      ...displayed, revision: displayed.revision + 1,
      project: { ...displayed.project, controls: [fixedControl, { ...boundControl, hosts: null }] },
    } }));
    await expect(bound).toContainText('CAMERA ADDRESS MISSING OR BLOCKED');
    await expect(bound.locator('iframe')).toHaveCount(0);
    await expect(cameraHeading(fixed, 'camera-a.localhost/fixed')).toBeVisible();
    await page.unroute('**/api/project/active');
    await save({ ...active, controls: [boundControl], layout: { width: 620, height: 400, boxes: {
      'bound-camera': { x: 10, y: 10, width: 400, height: 280 },
    } } });
    await page.goto('/runtime');
    const box = page.locator('[data-canvas-object="bound-camera"]');
    await expect(cameraHeading(box, 'camera-a.localhost/view')).toBeVisible();
    expect((await box.boundingBox()).width).toBe(400);
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    await save(original.active);
    await save(original.draft, false);
  }
});
