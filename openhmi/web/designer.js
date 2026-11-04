/* GrapesJS core supplies the visual editor; Python supplies simulated tag data. */
const status = document.querySelector('#status');
const runtime = document.querySelector('#runtime');
const editor = grapesjs.init({
  container: '#designer', height: '75vh', storageManager: false,
  telemetry: false, noticeOnUnload: false,
  canvas: { styles: ['/static/style.css'] },
});
const catalog = [
  { type: 'numeric-display', label: 'Numeric display', address: 'TankLevel', initial: '42' },
  { type: 'indicator', label: 'Indicator', address: 'MotorRunning', initial: 'ON' },
];
for (const control of catalog) {
  editor.DomComponents.addType(control.type, {
    model: { defaults: {
      tagName: 'div', name: control.label, droppable: false, editable: false,
      attributes: { 'data-control': control.type, 'data-address': control.address },
      style: { display: 'inline-block', margin: '12px', padding: '24px',
        'min-width': '180px', border: '2px solid #56718b', 'border-radius': '8px',
        'font-size': '22px', background: '#ffffff', color: '#15202d' },
      components: control.initial,
      traits: [{ type: 'text', name: 'data-address', label: 'PLCAddressValue' }],
    } },
  });
  editor.BlockManager.add(control.type, {
    label: control.label, category: 'HMI controls', content: { type: control.type },
  });
}
editor.addComponents(catalog.map(control => ({ type: control.type })));
editor.Css.setRule('body', { 'min-height': '100vh', background: '#eff4f9' });
editor.on('load', () => editor.Panels.getButton('views', 'open-blocks').set('active', true));
let timer;
let generation = 0;

function message(text) { status.textContent = text; }

document.querySelector('#save').onclick = () => {
  try {
    localStorage.setItem('openhmi.prototype.v1', JSON.stringify(editor.getProjectData()));
    message('Saved in this browser. Simulation-only prototype format.');
  } catch (error) { message(`Save failed: ${error.message}`); }
};
document.querySelector('#load').onclick = () => {
  try {
    const saved = localStorage.getItem('openhmi.prototype.v1');
    if (!saved) { message('No saved screen in this browser.'); return; }
    editor.loadProjectData(JSON.parse(saved));
    message('Loaded saved screen.');
  } catch (error) { message(`Load failed: ${error.message}`); }
};

async function refresh(run) {
  try {
    const response = await fetch('/api/tags', { signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const { values } = await response.json();
    if (run !== generation) return;
    for (const element of runtime.querySelectorAll('[data-control]')) {
      const address = element.dataset.address;
      if (!Object.hasOwn(values, address)) {
        element.textContent = `${address}: Unknown tag`;
        element.style.background = '#ffe3b6';
      } else {
        const value = values[address];
        element.textContent = `${address}: ${element.dataset.control === 'indicator' ? (value ? 'ON' : 'OFF') : value}`;
        element.style.background = element.dataset.control === 'indicator' && value ? '#a7e4bf' : '#ffffff';
      }
    }
    message('Runtime / Python simulator / polling every 500 ms');
  } catch (error) {
    if (run !== generation) return;
    for (const element of runtime.querySelectorAll('[data-control]')) {
      element.textContent = `${element.dataset.address}: Disconnected`;
      element.style.background = '#ffcece';
    }
    message(`Simulator unavailable: ${error.message}`);
  }
  if (run === generation) timer = setTimeout(() => refresh(run), 500);
}

document.querySelector('#run').onclick = () => {
  runtime.replaceChildren();
  function render(components) {
    for (const component of components.models) {
      const type = component.get('type');
      if (catalog.some(control => control.type === type)) {
        const element = document.createElement('div');
        element.dataset.control = type;
        element.dataset.address = component.getAttributes()['data-address'] || '';
        // Render only catalog components and a bounded set of layout properties.
        // Do not execute exported HTML, scripts, event attributes or CSS URLs.
        const style = component.getStyle();
        for (const key of ['margin', 'padding', 'width', 'height', 'min-width', 'font-size']) {
          if (/^\d+(\.\d+)?(px|%|rem|em)$/.test(style[key] || '')) {
            element.style.setProperty(key, style[key]);
          }
        }
        runtime.append(element);
      } else { render(component.components()); }
    }
  }
  render(editor.getWrapper().components());
  document.querySelector('#designer').hidden = true;
  runtime.hidden = false;
  document.querySelector('#run').hidden = true;
  document.querySelector('#design').hidden = false;
  document.querySelector('#save').disabled = true;
  document.querySelector('#load').disabled = true;
  clearTimeout(timer);
  refresh(++generation);
};
document.querySelector('#design').onclick = () => {
  ++generation;
  clearTimeout(timer);
  runtime.hidden = true;
  document.querySelector('#designer').hidden = false;
  document.querySelector('#run').hidden = false;
  document.querySelector('#design').hidden = true;
  document.querySelector('#save').disabled = false;
  document.querySelector('#load').disabled = false;
  message('Designer / simulation only. Use Settings to edit PLCAddressValue.');
  editor.refresh();
};
