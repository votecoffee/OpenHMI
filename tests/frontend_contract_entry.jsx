// Exercise production palette defaults and serializers without a DOM or PLC.
import { createConfig } from '../frontend/controls.jsx';
import { controlTypes, toEditor, toProject, scopedScreen } from '../frontend/model.mjs';
import { resolveFaceplateControl } from '../frontend/faceplate-model.mjs';
import { api, uploadProjectImage } from '../frontend/api.mjs';
import { readLatestCommand, commandHistoryPath, commandTransactionPath } from '../frontend/command-api.mjs';
import { commandStates } from '../frontend/command-status.mjs';
import { listProjectImages, isProjectImagePage } from '../frontend/image-api.mjs';
import { sendCaptureCommand } from '../frontend/trend-api.mjs';
import { publicationStatus, claimPublicationStation, releasePublicationStation } from '../frontend/identity-api.mjs';
import { writeControlValue, activateControl, renewSubscription } from '../frontend/runtime-api.mjs';
import { saveProjectDraft, applyLiveProject } from '../frontend/project-api.mjs';
import { acknowledgeAlarms } from '../frontend/alarm-api.mjs';
import { engineeringCatalog } from '../frontend/engineering.jsx';
import { createPaletteFields } from '../frontend/palette-fields.jsx';
import { paletteFactories } from '../frontend/palette-components.jsx';

export async function contract(request) {
  if (request.operation === 'image_pages') return request.pages.map(isProjectImagePage);
  if (request.operation === 'engineering') {
    const catalog = engineeringCatalog(request.catalog, request.project, request.template ?? null);
    const config = createConfig(catalog);
    return { catalog, modeTags: config.components.ModeSelector.fields.tag.options,
      sliderTags: config.components.Slider.fields.tag.options,
      components: Object.keys(config.components) };
  }
  if (request.operation === 'catalogs') {
    const first = createConfig(request.catalogs[0]);
    first.components.NumericInput.fields.tag.options.push({ label: 'Poison', value: 'Poison' });
    first.components.MultiState.defaultProps.states[0].label = 'Mutated';
    return request.catalogs.map(catalog => {
      const config = createConfig(catalog);
      return {
        dropdown: config.components.Dropdown.defaultProps,
        slider: config.components.Slider.defaultProps,
        numericTags: config.components.NumericInput.fields.tag.options,
        sliderTags: config.components.Slider.fields.tag.options,
        modeTags: config.components.ModeSelector.fields.tag.options,
        states: config.components.MultiState.defaultProps.states,
      };
    });
  }
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
    const fields = createPaletteFields(request.catalog);
    const families = paletteFactories.map(factory => Object.keys(factory(request.catalog, fields, () => config)));
    return { types: controlTypes, components: Object.keys(config.components), inputTypes: config.categories.inputs.components,
      families, categories: Object.values(config.categories).map(category => category.components),
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
  if (request.operation === 'requests' || request.operation === 'lifecycle_requests' || request.operation === 'service_requests' || request.operation === 'command_queries' || request.operation === 'image_queries') {
    const requests = [];
    globalThis.fetch = async (path, options) => {
      const upload = options.body instanceof Blob;
      requests.push({ path, method: options.method, headers: options.headers,
        keepalive: options.keepalive, body: upload ? null : options.body && JSON.parse(options.body),
        ...(upload ? { upload: { name: options.body.name, type: options.body.type, bytes: Array.from(new Uint8Array(await options.body.arrayBuffer())) },
          timeout: options.signal instanceof AbortSignal } : {}) });
      return new Response(JSON.stringify({ ok: true, project_instance: 'a'.repeat(32) }), {
        headers: { 'Content-Type': 'application/json' },
      });
    };
    await api('/api/project');
    if (request.operation === 'image_queries') {
      await listProjectImages();
      await listProjectImages({ before: 42 });
      await listProjectImages({ search: '设备 / %.png?#' });
      await listProjectImages({ before: '9223372036854775807', search: '设备 / %.png?#', limit: 32 });
      await listProjectImages({ limit: 1 });
      await listProjectImages({ search: 'x'.repeat(100) });
      return requests.slice(1);
    }
    if (request.operation === 'command_queries') {
      await readLatestCommand('设备 / Cycle?#');
      await api(commandHistoryPath());
      await api(commandHistoryPath({ limit: 200, command: '设备 / Cycle?#', state: 'unresolved', before: '9223372036854775807' }));
      for (const state of ['unresolved', ...commandStates]) await api(commandHistoryPath({ state }));
      await api(commandTransactionPath(123));
      await api(commandTransactionPath('9223372036854775807', true));
      return { requests: requests.slice(1), states: ['', 'unresolved', ...commandStates] };
    }
    if (request.operation === 'service_requests') {
      for (const [action, captureId] of [['start', 0], ['stop', 123], ['delete', 123]]) {
        await sendCaptureCommand('设备 / trend?#', action, captureId);
      }
      await publicationStatus();
      await claimPublicationStation('station 设备');
      await claimPublicationStation('station 设备', true);
      await releasePublicationStation('station 设备');
      await uploadProjectImage(new File([new Uint8Array([137, 80, 78, 71])], '机器 pic #.png', { type: 'image/png' }));
      return requests.slice(1);
    }
    if (request.operation === 'lifecycle_requests') {
      await saveProjectDraft(request.project, 123);
      await applyLiveProject(123, '  更改画面  ');
      await applyLiveProject(124, '  ');
      await acknowledgeAlarms(1, '已检查');
      await acknowledgeAlarms(null, 'All inspected');
      await acknowledgeAlarms(null, 'Selected inspected', [2, 3]);
      return requests.slice(1);
    }
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
