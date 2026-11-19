// Exercise production palette defaults and serializers without a DOM or PLC.
import { createConfig } from '../frontend/controls.jsx';
import { controlTypes, toEditor, toProject, scopedScreen } from '../frontend/model.mjs';
import { resolveFaceplateControl } from '../frontend/faceplate-model.mjs';
import { api } from '../frontend/api.mjs';
import { writeControlValue, activateControl, renewSubscription } from '../frontend/runtime-api.mjs';

export async function contract(request) {
  if (request.operation === 'defaults') {
    const config = createConfig(request.catalog);
    const content = Object.entries(config.components).map(([type, component]) => ({
      type, props: { ...component.defaultProps, ...request.bindings?.[type], id: 'contract_' + type },
    }));
    const editor = { root: { props: config.root.defaultProps }, content };
    const selections = content.flatMap(item => Object.entries(config.components[item.type].fields)
      .filter(([, field]) => field.type === 'select')
      .flatMap(([name, field]) => field.options.filter(option => option.value !== '').map(option => ({
        component: item.type, field: name, value: option.value,
        control: toProject({ ...editor, content: [{ ...item, props: { ...item.props, [name]: option.value } }] }).controls[0],
      }))));
    return { types: controlTypes, components: Object.keys(config.components), inputTypes: config.categories.inputs.components,
      project: toProject(editor), selections };
  }
  if (request.operation === 'roundtrip') {
    return request.projects.map(project => toProject(toEditor(project), project));
  }
  if (request.operation === 'faceplates') {
    const original = JSON.stringify(request.project);
    const screen = scopedScreen(request.project, request.screen);
    const controls = screen.controls.flatMap(instance => {
      const template = request.project.faceplates.find(item => item.id === instance.template);
      return template.controls.map(control => resolveFaceplateControl(control, instance));
    });
    if (JSON.stringify(request.project) !== original) throw new Error('Faceplate resolution mutated the project');
    return controls;
  }
  if (request.operation === 'requests') {
    const requests = [];
    globalThis.fetch = async (path, options) => {
      requests.push({ path, method: options.method, headers: options.headers,
        keepalive: options.keepalive, body: options.body && JSON.parse(options.body) });
      return new Response(JSON.stringify({ ok: true, project_instance: 'a'.repeat(32) }), {
        headers: { 'Content-Type': 'application/json' },
      });
    };
    await api('/api/project');
    for (const value of [0, 0.25, false, true, '001 设备', '']) {
      await writeControlValue('details__motor__speed', value, 123);
    }
    await activateControl('details__motor__start', 123);
    await renewSubscription('contract-viewer', ['overview', 'details'], 'MotorA', 42);
    await renewSubscription('contract-viewer', [], '', 43, true);
    return requests.slice(1);
  }
  throw new Error('Unknown frontend contract operation');
}
