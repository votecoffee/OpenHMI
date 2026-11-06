import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8766', hasTouch: true });

test('input palette drag and drop and secured live entry', async ({ page }) => {
  test.setTimeout(60000);
  const login = await page.request.post('/api/security/login', {
    data: { name: 'admin', password: 'SecurityTestOnly-2026!' },
  });
  expect(login.ok()).toBe(true);
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const current = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { project, expected_revision: current.draft_revision } });
    expect(saved.ok(), await saved.text()).toBe(true);
    if (apply) {
      const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } });
      expect(applied.ok(), await applied.text()).toBe(true);
    }
  }
  try {
    await save({
      title: 'Input palette station',
      tags: [
        { name: 'SpeedChoice', type: 'integer', initial: 0, writable: true },
        { name: 'ColorChoice', type: 'string', initial: 'r', writable: true },
        { name: 'Checked', type: 'boolean', initial: false, writable: true },
        { name: 'Toggled', type: 'boolean', initial: false, writable: true },
        { name: 'Notes', type: 'string', initial: 'First', writable: true },
      ],
      controls: [
        { id: 'color', kind: 'radio_group', tag: 'ColorChoice', label: 'Color',
          options: [{ value: 'r', label: 'Red' }, { value: 'b', label: 'Blue' }] },
        { id: 'checked', kind: 'checkbox', tag: 'Checked', label: 'Check' },
        { id: 'toggled', kind: 'toggle_switch', tag: 'Toggled', label: 'Enable' },
        { id: 'notes', kind: 'text_area', tag: 'Notes', label: 'Notes' },
      ],
    });
    await page.goto('/');
    const block = page.getByRole('button', { name: 'Dropdown', exact: true });
    await block.scrollIntoViewIfNeeded();
    const source = await block.boundingBox();
    const target = await page.locator('.hmi-grid').boundingBox();
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
    await page.mouse.down();
    await page.mouse.move(target.x + 100, target.y + 90, { steps: 10 });
    await page.mouse.move(target.x + 110, target.y + 100, { steps: 2 });
    await page.mouse.up();
    await expect(page.locator('[data-control="dropdown"]')).toHaveCount(1);
    await page.locator('[data-control="dropdown"] .hmi-label').click();
    await page.getByRole('textbox', { name: 'Choice label', exact: true }).nth(1).fill('Fast');
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('saved');
    await page.getByRole('button', { name: 'Apply live', exact: true }).click();
    await expect(page.getByRole('status', { name: 'Draft status' })).toContainText('Applied live');

    await page.goto('/runtime');
    const dropdown = page.getByRole('combobox', { name: 'Dropdown', exact: true });
    await dropdown.selectOption({ label: 'Fast' });
    const blue = page.getByRole('radio', { name: 'Blue', exact: true });
    await blue.click();
    await expect(blue).toBeChecked();
    const checkbox = page.getByRole('checkbox', { name: 'Check', exact: true });
    await checkbox.click();
    await expect(checkbox).toBeChecked();
    const toggle = page.getByRole('switch', { name: 'Enable', exact: true });
    await toggle.click();
    await expect(toggle).toBeChecked();
    await expect(dropdown).toHaveValue('1');

    await page.getByRole('button', { name: 'Open keyboard for Notes' }).click();
    const dialog = page.getByRole('dialog', { name: 'Text entry: Notes' });
    const entry = dialog.locator('textarea');
    await entry.fill('First');
    await dialog.getByRole('button', { name: 'New line', exact: true }).click();
    await dialog.getByRole('button', { name: 'a', exact: true }).click();
    await expect(entry).toHaveValue('First\na');
    await dialog.getByRole('button', { name: 'Accept entry', exact: true }).click();
    await expect(dialog).toBeHidden();
    const data = await (await page.request.get('/api/tags')).json();
    expect(data.values).toMatchObject({
      SpeedChoice: 1, ColorChoice: 'b', Checked: true, Toggled: true, Notes: 'First\na',
    });
    data.samples.Checked = { quality: 'stale', age_seconds: 4 };
    await page.route('**/api/tags', route => route.fulfill({ json: data }));
    await expect(page.locator('[data-control="checkbox"]')).toContainText('STALE DATA');
    await expect(checkbox).toBeHidden();
    await expect(toggle).toBeEnabled();
  } finally {
    await save(original.active);
    if (JSON.stringify(original.draft) !== JSON.stringify(original.active)) await save(original.draft, false);
  }
});

test('machine state, mode selection and permissives use live quality and separate feedback', async ({ page }) => {
  const login = await page.request.post('/api/security/login', {
    data: { name: 'admin', password: 'SecurityTestOnly-2026!' },
  });
  expect(login.ok()).toBe(true);
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply = true) {
    const current = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { project, expected_revision: current.draft_revision } });
    expect(saved.ok(), await saved.text()).toBe(true);
    if (apply) {
      const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } });
      expect(applied.ok(), await applied.text()).toBe(true);
    }
  }
  const states = [
    { value: 0, label: 'Manual', symbol: 'square', color: '#555555' },
    { value: 1, label: 'Auto', symbol: 'circle', color: '#333333' },
  ];
  const project = {
    title: 'Machine state station',
    tags: [
      { name: 'ModeRequest', type: 'integer', initial: 0, writable: true },
      { name: 'ModeFeedback', type: 'integer', initial: 0 },
      { name: 'PilotMotorRunning', type: 'boolean', initial: true },
      { name: 'PilotFaulted', type: 'boolean', initial: false },
    ],
    controls: [
      { id: 'state', kind: 'multi_state', label: 'Actual machine state', tag: 'ModeFeedback', states },
      { id: 'mode', kind: 'mode_selector', label: 'Operating mode', tag: 'ModeRequest', confirmed_tag: 'ModeFeedback',
        states, presentation: 'segments', security_groups: ['Administrators'] },
      { id: 'checks', kind: 'permissives', label: 'Start permissives', checks: [
        { tag: 'PilotMotorRunning', label: 'Motor must be stopped', expected: false },
        { tag: 'PilotFaulted', label: 'No process alarm', expected: false },
      ] },
    ],
  };
  try {
    await save(project);
    await page.goto('/');
    await page.locator('[data-control="mode_selector"] .hmi-label').click();
    await expect(page.getByRole('combobox', { name: 'Mode request tag', exact: true })).toHaveValue(JSON.stringify({ value: 'ModeRequest' }));
    await expect(page.getByRole('combobox', { name: 'PLC confirmed mode tag', exact: true })).toHaveValue(JSON.stringify({ value: 'ModeFeedback' }));

    await page.goto('/runtime');
    const state = page.locator('[data-control="multi_state"]');
    const mode = page.locator('[data-control="mode_selector"]');
    const permissives = page.locator('[data-control="permissives"]');
    await expect(state).toContainText('Manual');
    await expect(permissives.getByRole('listitem').filter({ hasText: 'Motor must be stopped' })).toContainText('Blocked');
    await expect(permissives.getByRole('listitem').filter({ hasText: 'No process alarm' })).toContainText('Ready');
    await mode.getByRole('button', { name: 'Auto', exact: true }).click();
    await expect(mode.getByRole('button', { name: 'Auto', exact: true })).toHaveAttribute('aria-pressed', 'true');
    expect((await (await page.request.get('/api/tags')).json()).values.ModeRequest).toBe(0);
    await mode.getByRole('button', { name: 'Request mode', exact: true }).click();
    await expect(mode).toContainText('Waiting for PLC confirmation');
    const values = (await (await page.request.get('/api/tags')).json()).values;
    expect([values.ModeRequest, values.ModeFeedback]).toEqual([1, 0]);
    await expect(state).toContainText('Manual');

    await page.route('**/api/tags', async route => {
      const response = await route.fetch();
      const data = await response.json();
      data.samples.ModeFeedback = { quality: 'stale', age_seconds: 4, error: 'Test feedback aged out' };
      data.samples.PilotMotorRunning = { quality: 'bad', error: 'Test permissive unavailable' };
      await route.fulfill({ response, json: data });
    });
    await expect(state).toContainText('STALE DATA');
    await expect(mode.getByRole('button', { name: 'Manual', exact: true })).toBeDisabled();
    await expect(permissives.getByRole('listitem').filter({ hasText: 'Motor must be stopped' })).toContainText('BAD DATA');
  } finally {
    await save(original.active);
    if (JSON.stringify(original.draft) !== JSON.stringify(original.active)) await save(original.draft, false);
  }
});

test('runtime language applies to login, keypad, and Unicode text entry', async ({ page }) => {
  test.setTimeout(60000);
  const password = 'SecurityTestOnly-2026!';
  const admin = await page.request.post('/api/security/login', { data: { name: 'admin', password } });
  expect(admin.ok()).toBe(true);
  const original = await (await page.request.get('/api/project')).json();
  async function save(project, apply) {
    const state = await (await page.request.get('/api/project')).json();
    const draft = await page.request.put('/api/project/draft', { data: { project, expected_revision: state.draft_revision } });
    expect(draft.ok(), await draft.text()).toBe(true);
    if (apply) expect((await page.request.post('/api/project/apply', {
      data: { expected_revision: (await draft.json()).draft_revision },
    })).ok()).toBe(true);
  }
  async function expectCompactDialog(dialog) {
    const layout = await dialog.evaluate(element => ({
      overflow: element.scrollWidth > element.clientWidth,
      left: element.getBoundingClientRect().left,
      right: element.getBoundingClientRect().right,
      narrowestKey: Math.min(...Array.from(element.querySelectorAll('.touch-keys button'),
        button => button.getBoundingClientRect().width)),
    }));
    expect(layout.left).toBeGreaterThanOrEqual(0);
    expect(layout.right).toBeLessThanOrEqual(360);
    expect(layout.overflow).toBe(false);
    expect(layout.narrowestKey).toBeGreaterThanOrEqual(44);
  }
  try {
    const project = structuredClone(original.active);
    project.languages.push({ code: 'es', name: 'Español', flag: 'es', translations: {
      'ui.hmiLogin': 'Acceso HMI', 'ui.openHmiLogin': 'Abrir acceso HMI', 'ui.signOutHmi': 'Cerrar sesión HMI',
      'ui.hmiUser': 'Usuario HMI', 'ui.passwordKeyboard': 'Teclado de contraseña', 'ui.passwordEntry': 'Contraseña',
      'ui.backspaceKey': 'Borrar el carácter anterior a la posición del cursor',
      'ui.signInHmi': 'Iniciar sesión', 'ui.acceptEntry': 'Aceptar entrada', 'ui.entryLabel': 'Entrada',
      'ui.openNumericKeypad': 'Abrir teclado numérico para {label}', 'ui.numericEntryTitle': 'Entrada numérica: {label}',
      'ui.allowedNumericRange': 'Rango permitido: {low} a {high}', 'control.localized_number.label': 'Nivel',
      'ui.openTextKeyboard': 'Abrir teclado para {label}', 'ui.textEntryTitle': 'Entrada de texto: {label}',
      'ui.textKeyboard': 'Teclado de texto', 'control.localized_text.label': 'Mensaje',
    } });
    project.tags.push({ name: 'LocalizedEntry', type: 'string', initial: '', writable: true });
    project.controls.push(
      { id: 'localized_number', kind: 'input', label: 'Level', tag: 'TankLevel', minimum: 0, maximum: 50 },
      { id: 'localized_text', kind: 'text_input', label: 'Message', tag: 'LocalizedEntry', max_length: 8 },
    );
    await save(project, true);
    await page.goto('/runtime');
    await page.getByRole('button', { name: 'Language: English', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Español', exact: true }).click();
    await page.getByRole('button', { name: 'Cerrar sesión HMI', exact: true }).click();
    await page.getByRole('button', { name: 'Abrir acceso HMI', exact: true }).click();
    const login = page.getByRole('dialog', { name: 'Acceso HMI', exact: true });
    await page.setViewportSize({ width: 360, height: 600 });
    await expectCompactDialog(login);
    await login.getByLabel('Usuario HMI', { exact: true }).fill('admin');
    await login.getByRole('button', { name: 'Teclado de contraseña', exact: true }).click();
    const keyboard = page.getByRole('dialog', { name: 'Teclado de contraseña', exact: true });
    await expectCompactDialog(keyboard);
    const secret = keyboard.getByLabel('Contraseña', { exact: true });
    await expect(secret).toHaveAttribute('type', 'password');
    await secret.fill(password.slice(1));
    await secret.press('Home');
    await keyboard.getByRole('button', { name: 'Shift', exact: true }).tap();
    await keyboard.getByRole('button', { name: 'S', exact: true }).tap();
    await expect(secret).toBeFocused();
    await keyboard.getByRole('button', { name: 'Aceptar entrada', exact: true }).click();
    await login.getByRole('button', { name: 'Iniciar sesión', exact: true }).click();
    await expect(login).not.toBeVisible();

    await page.getByRole('button', { name: 'Abrir teclado numérico para Nivel', exact: true }).click();
    const numeric = page.getByRole('dialog', { name: 'Entrada numérica: Nivel', exact: true });
    await expectCompactDialog(numeric);
    const numberEntry = numeric.getByLabel('Entrada', { exact: true });
    await numberEntry.fill('55');
    await numeric.getByRole('button', { name: 'Aceptar entrada', exact: true }).click();
    await expect(numeric.getByRole('alert')).toHaveText('Rango permitido: 0 a 50');
    await numberEntry.press('Home');
    await numberEntry.press('Shift+ArrowRight');
    await numeric.getByRole('button', { name: '4', exact: true }).tap();
    await expect(numberEntry).toHaveValue('45');
    await numeric.press('Escape');
    await page.getByRole('button', { name: 'Abrir teclado para Mensaje', exact: true }).click();
    const text = page.getByRole('dialog', { name: 'Entrada de texto: Mensaje', exact: true });
    await expectCompactDialog(text);
    await expect(text.getByRole('group', { name: 'Teclado de texto' })).toBeVisible();
    const entry = text.getByLabel('Entrada', { exact: true });
    await entry.fill('设备🛠x');
    await entry.press('End');
    await entry.press('ArrowLeft');
    await text.getByRole('button', { name: 'Borrar el carácter anterior a la posición del cursor', exact: true }).tap();
    await expect(entry).toHaveValue('设备x');
    await entry.press('Shift+ArrowRight');
    const aKey = text.getByRole('button', { name: 'a', exact: true });
    await aKey.focus();
    await aKey.press('Enter');
    await expect(aKey).toBeFocused();
    await expect(entry).toHaveValue('设备a');
    await text.getByRole('button', { name: 'Aceptar entrada', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LocalizedEntry).toBe('设备a');
    const inline = page.getByLabel('Mensaje new value', { exact: true });
    await inline.fill('old');
    await page.getByRole('button', { name: 'Abrir teclado para Mensaje', exact: true }).click();
    await expect(entry).toHaveValue('old');
    const rebound = structuredClone(project);
    rebound.tags.push({ name: 'NewEntry', type: 'string', initial: 'new', writable: true });
    rebound.controls.find(control => control.id === 'localized_text').tag = 'NewEntry';
    const displayed = await (await page.request.get('/api/project/active')).json();
    const activeEndpoint = '**/api/project/active';
    await page.route(activeEndpoint, route => route.fulfill({ json: displayed }));
    await save(rebound, true);
    const rejection = 'The applied project changed. Reopen the keypad or clear and re-enter the value.';
    const rejectedWrite = () => page.waitForResponse(response =>
      response.url().endsWith('/api/controls/localized_text/value') && response.request().method() === 'PUT',
    { timeout: 5000 });
    const [touchResult] = await Promise.all([rejectedWrite(),
      text.getByRole('button', { name: 'Aceptar entrada', exact: true }).click()]);
    expect(touchResult.status()).toBe(409);
    await expect(text.getByRole('alert')).toHaveText(rejection);
    await text.press('Escape');
    const [inlineResult] = await Promise.all([rejectedWrite(), inline.press('Enter')]);
    expect(inlineResult.status()).toBe(409);
    await expect(page.getByText(rejection, { exact: true })).toBeVisible();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.NewEntry).toBe('new');
    await page.unroute(activeEndpoint);
    const active = await (await page.request.get('/api/project/active')).json();
    await expect(page.getByText(`Live screen / revision ${active.revision}`)).toBeVisible();
    await page.getByRole('button', { name: 'Abrir teclado para Mensaje', exact: true }).click();
    await expect(entry).toHaveValue('new');
    await entry.fill('fresh');
    await text.getByRole('button', { name: 'Aceptar entrada', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.NewEntry).toBe('fresh');
  } finally {
    await page.request.post('/api/security/login', { data: { name: 'admin', password } });
    await save(original.active, true);
    await save(original.draft, false);
  }
});

test('touch entry, colored lock legend, login popup and explicit PLC identity station', async ({ page }) => {
  test.setTimeout(90000);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/runtime');
  async function login(name) {
    await page.getByRole('button', { name: 'Open HMI login', exact: true }).first().click();
    const dialog = page.getByRole('dialog', { name: 'HMI login', exact: true });
    await dialog.getByLabel('HMI user', { exact: true }).fill(name);
    await dialog.getByLabel('HMI password', { exact: true }).fill('SecurityTestOnly-2026!');
    await dialog.getByRole('button', { name: 'Sign in to HMI', exact: true }).click();
    await expect(dialog).not.toBeVisible();
  }
  await login('admin');
  let version = (await (await page.request.get('/api/security')).json()).version;
  for (const fields of [{ operation: 'group', name: 'TouchOperators', permissions: ['runtime.write', 'runtime.operate', 'identity.publish'], color: '#527d80' }, { operation: 'user', name: 'touch_operator', password: 'SecurityTestOnly-2026!', groups: ['TouchOperators'] }]) {
    const response = await page.request.put('/api/security', { data: { ...fields, expected_version: version, reason: 'Synthetic touch fixture' } });
    expect(response.ok()).toBe(true); version = (await response.json()).version;
  }
  const original = await (await page.request.get('/api/project')).json();
  async function install(project) {
    const current = await (await page.request.get('/api/project')).json();
    const saved = await page.request.put('/api/project/draft', { data: { project, expected_revision: current.draft_revision } }); expect(saved.ok()).toBe(true);
    const applied = await page.request.post('/api/project/apply', { data: { expected_revision: (await saved.json()).draft_revision } }); expect(applied.ok()).toBe(true);
  }
  const project = structuredClone(original.active);
  project.tags.push({ name: 'TouchLow', type: 'number', initial: 10, writable: true }, { name: 'TouchHigh', type: 'number', initial: 50, writable: true }, { name: 'TouchPermit', type: 'boolean', initial: true }, { name: 'LoginName', type: 'string', initial: '', writable: true }, { name: 'LoginBits', type: 'integer', initial: 0, writable: true });
  project.controls.push({ id: 'touch_number', kind: 'input', label: 'Touch number', tag: 'TankLevel', minimum_tag: 'TouchLow', maximum_tag: 'TouchHigh', enabled_tag: 'TouchPermit', security_groups: ['TouchOperators'] }, { id: 'touch_text', kind: 'text_input', label: 'Touch text', tag: 'OperatorText', min_length: 1, max_length: 4, security_groups: ['TouchOperators'] }, { id: 'who', kind: 'current_user', label: 'Operator login' });
  project.identity_publication = { enabled: true, username_tag: 'LoginName', privileges_tag: 'LoginBits', username_bytes: 82, bits: [{ bit: 0, source: 'permission', name: 'runtime.operate' }, { bit: 3, source: 'group', name: 'TouchOperators' }] };
  try {
    await install(project); await page.reload();
    await page.getByRole('button', { name: 'Sign out of HMI', exact: true }).click();
    await page.getByRole('button', { name: 'Locked: Touch number', exact: true }).click();
    const legend = page.getByRole('dialog', { name: 'Security group legend', exact: true });
    await expect(legend).toContainText('TouchOperators');
    await expect(legend.locator('.security-swatch')).toHaveCSS('background-color', 'rgb(82, 125, 128)');
    await legend.getByRole('button', { name: 'Close Security group legend', exact: true }).click();
    await login('touch_operator');
    await expect(page.locator('[data-control="current_user"]')).toContainText('touch_operator');
    let permitBad = false;
    await page.route('**/api/tags', async route => {
      const response = await route.fetch();
      const state = await response.json();
      state.values.TouchPermit = false;
      state.samples.TouchHigh = { quality: 'stale', age_seconds: 4, error: 'Synthetic stale maximum' };
      if (permitBad) state.samples.TouchPermit = { quality: 'bad', quality_reason: 'disconnected' };
      await route.fulfill({ response, json: state });
    });
    const keypad = page.getByRole('button', { name: 'Open numeric keypad for Touch number', exact: true });
    const maximum = page.getByRole('button', { name: 'Inspect TouchHigh quality (Maximum · STALE DATA)', exact: true });
    await expect(page.getByText('Enable tag TouchPermit is off', { exact: true })).toBeVisible();
    await expect(keypad).toBeDisabled();
    await maximum.tap();
    const quality = page.getByRole('dialog', { name: 'Tag quality details', exact: true });
    await expect(quality).toContainText('Synthetic stale maximum');
    await quality.getByRole('button', { name: 'Close Tag quality details' }).tap();
    permitBad = true;
    await expect(page.getByRole('button', { name: 'Inspect TouchPermit quality (Enable tag · PLC COMM LOSS)', exact: true })).toBeEnabled();
    await page.unrouteAll({ behavior: 'wait' });
    await expect(keypad).toBeEnabled();
    await keypad.click();
    const numeric = page.getByRole('dialog', { name: 'Numeric entry: Touch number', exact: true });
    await numeric.getByLabel('Entry', { exact: true }).fill('55');
    await numeric.getByRole('button', { name: 'Accept entry', exact: true }).click();
    await expect(numeric.getByRole('alert')).toContainText('Allowed range');
    await numeric.getByRole('button', { name: 'Clear', exact: true }).click();
    await numeric.getByRole('button', { name: '2', exact: true }).click(); await numeric.getByRole('button', { name: '5', exact: true }).click();
    await page.route('**/api/tags', async route => {
      const response = await route.fetch();
      const state = await response.json();
      state.samples.TouchHigh = { quality: 'stale', error: 'Synthetic maximum loss during entry' };
      await route.fulfill({ response, json: state });
    });
    const accept = numeric.getByRole('button', { name: 'Accept entry', exact: true });
    const entry = numeric.getByLabel('Entry', { exact: true });
    await expect(numeric.getByRole('status')).toHaveText('Maximum TouchHigh · STALE DATA');
    await expect(accept).toBeDisabled();
    await expect(entry).toHaveValue('25');
    await page.unrouteAll({ behavior: 'wait' });
    await expect(accept).toBeEnabled();
    await expect(entry).toHaveValue('25');
    await accept.click();
    await expect(numeric).not.toBeVisible();
    await expect(page.locator('[data-control="input"]').filter({ hasText: 'Touch number' })).toContainText('25.0');
    await page.getByRole('button', { name: 'Open keyboard for Touch text', exact: true }).click();
    const text = page.getByRole('dialog', { name: 'Text entry: Touch text', exact: true });
    await text.getByRole('button', { name: 'a', exact: true }).click(); await text.getByRole('button', { name: 'b', exact: true }).click();
    if (process.env.OPENHMI_TOUCH_SCREENSHOT) await page.screenshot({ path: process.env.OPENHMI_TOUCH_SCREENSHOT, fullPage: true });
    await text.getByRole('button', { name: 'Accept entry', exact: true }).click();
    await expect(page.locator('[data-control="text_input"]')).toContainText('ab');
    await page.getByRole('button', { name: 'Publish this station login', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LoginName).toBe('touch_operator');
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LoginBits).toBe(9);
    const panel = page.getByRole('region', { name: 'PLC login publication' });
    const renew = '**/api/security/publication/claim?renew=true';
    const status = '**/api/security/publication';
    let renewals = 0;
    await page.route(renew, route => { renewals += 1; return route.fulfill({ json: {} }); });
    await page.route(status, route => route.fulfill({ status: 503, json: {} }));
    await expect(panel).toContainText('PLC identity status unavailable');
    await expect(panel).toContainText('Last received PLC identity');
    const stopPublishing = panel.getByRole('button', { name: 'Stop publishing this station' });
    const publish = panel.getByRole('button', { name: 'Publish this station login' });
    await expect(stopPublishing).toBeDisabled();
    await expect(publish).toBeDisabled();
    await page.unroute(status);
    await expect(panel).toContainText('Automatic renewal paused');
    await expect(stopPublishing).toBeEnabled();
    await page.waitForResponse(status);
    expect(renewals).toBe(1);
    await page.unroute(renew);
    await stopPublishing.click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LoginBits).toBe(0);
    await publish.click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LoginBits).toBe(9);
    await page.getByRole('button', { name: 'Sign out of HMI', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/api/tags')).json()).values.LoginBits).toBe(0);
    expect(errors).toEqual([]);
  } finally {
    await page.request.post('/api/security/login', { data: { name: 'admin', password: 'SecurityTestOnly-2026!' } });
    const current = await (await page.request.get('/api/project')).json();
    if (current.active.identity_publication.enabled) { const disabled = structuredClone(current.active); disabled.identity_publication.enabled = false; await install(disabled); await expect.poll(async () => (await (await page.request.get('/api/security/publication')).json()).status).toBe('disabled'); }
    await install(original.active);
    const restored = await (await page.request.get('/api/project')).json();
    await page.request.put('/api/project/draft', { data: { project: original.draft, expected_revision: restored.draft_revision } });
  }
});
