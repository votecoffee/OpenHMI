export const controlTypes = {
  numeric: 'NumericDisplay', indicator: 'Indicator', button: 'ActionButton',
  analog: 'AnalogRange', alarm: 'AlarmIndicator',
};
const kinds = Object.fromEntries(Object.entries(controlTypes).map(([kind, type]) => [type, kind]));

export function toEditor(project) {
  return {
    root: { props: { title: project.title, columns: project.columns } },
    content: project.controls.map(({ kind, ...props }) => ({ type: controlTypes[kind], props })),
  };
}

export function toProject(data) {
  return {
    schema_version: 1, title: data.root.props.title, columns: Number(data.root.props.columns),
    controls: data.content.map(({ type, props }) => {
      const base = { kind: kinds[type], id: props.id, label: props.label };
      if (type === 'ActionButton') return { ...base, action: props.action };
      if (type === 'AlarmIndicator') return { ...base, tag: props.tag, priority: Number(props.priority) };
      if (type === 'Indicator') return { ...base, tag: props.tag, on_text: props.on_text ?? 'ON', off_text: props.off_text ?? 'OFF' };
      const numeric = { ...base, tag: props.tag, unit: props.unit, decimals: Number(props.decimals) };
      if (type === 'AnalogRange') {
        return { ...numeric, ...Object.fromEntries(['minimum', 'maximum', 'normal_low', 'normal_high'].map(key => [key, Number(props[key])])) };
      }
      return numeric;
    }),
  };
}
