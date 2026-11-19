// Exercise production palette defaults and serializers without a DOM or PLC.
import { createConfig } from '../frontend/controls.jsx';
import { controlTypes, toEditor, toProject } from '../frontend/model.mjs';

export function contract(request) {
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
    return { types: controlTypes, components: Object.keys(config.components),
      project: toProject(editor), selections };
  }
  if (request.operation === 'roundtrip') {
    return request.projects.map(project => toProject(toEditor(project), project));
  }
  throw new Error('Unknown frontend contract operation');
}
