export const controlTypes = {
  numeric: 'NumericDisplay', indicator: 'Indicator', button: 'ActionButton',
  analog: 'AnalogRange', tank: 'TankLevel', bar: 'BarGraph', radar: 'RadarChart', alarm: 'AlarmIndicator',
  recipe: 'SelectedRecipe',
  input: 'NumericInput',
  text_input: 'TextInput', current_user: 'CurrentUser',
  faceplate: 'Faceplate', trend: 'Trend', text: 'TextDisplay',
};
const kinds = Object.fromEntries(Object.entries(controlTypes).map(([kind, type]) => [type, kind]));

export function toEditor(project) {
  return {
    root: { props: { title: project.title, columns: project.columns, update_ms: project.update_ms || 500, screen_id: project.id || 'overview' } },
    content: project.controls.map(({ kind, ...props }) => {
      if (kind === 'trend') {
        const { tags, series, ...common } = props;
        return { type: 'Trend', props: { ...common, pens: { tags, series: series || {} } } };
      }
      return { type: controlTypes[kind], props };
    }),
  };
}

export function toProject(data, settings = {}) {
  return {
    ...settings,
    schema_version: 1, title: data.root.props.title, columns: Number(data.root.props.columns), update_ms: Number(data.root.props.update_ms || 500),
    controls: data.content.map(({ type, props }) => {
      const base = { kind: kinds[type], id: props.id, label: props.label, visible_tag: props.visible_tag || '', enabled_tag: props.enabled_tag || '', color_tag: props.color_tag || '', active_color: props.active_color || '#002878' };
      if (type === 'Faceplate') return { ...base, template: props.template, root_tag: props.root_tag };
      if (type === 'Trend') return { ...base, tags: props.pens?.tags ?? props.tags ?? ['TankLevel'],
        series: props.pens?.series ?? props.series ?? {}, seconds: Number(props.seconds ?? 300), recording: props.recording ?? null };
      if (type === 'RadarChart') return { ...base, series: props.series };
      if (type === 'BarGraph') return { ...base, series: props.series, unit: props.unit,
        minimum: Number(props.minimum), maximum: Number(props.maximum) };
      if (type === 'SelectedRecipe' || type === 'CurrentUser') return base;
      if (type === 'TextDisplay') return { ...base, tag: props.tag };
      if (type === 'TextInput') return { ...base, tag: props.tag, min_length: Number(props.min_length ?? 0), max_length: Number(props.max_length ?? 82), min_length_tag: props.min_length_tag || '', max_length_tag: props.max_length_tag || '', security_groups: props.security_groups || [] };
      if (type === 'ActionButton') return { ...base, action: props.action || '', mode: props.mode || 'python', command: props.command || '', target: props.target || '', value: props.value ?? false, screen: props.screen || 'overview', security_groups: props.security_groups || [] };
      if (type === 'AlarmIndicator') return { ...base, tag: props.tag, priority: Number(props.priority) };
      if (type === 'Indicator') return { ...base, tag: props.tag, on_text: props.on_text ?? 'ON', off_text: props.off_text ?? 'OFF' };
      const numeric = { ...base, tag: props.tag, unit: props.unit, decimals: Number(props.decimals) };
      if (type === 'NumericInput') return { ...numeric, minimum: Number(props.minimum), maximum: Number(props.maximum), minimum_tag: props.minimum_tag || '', maximum_tag: props.maximum_tag || '', security_groups: props.security_groups || [] };
      if (type === 'AnalogRange' || type === 'TankLevel') {
        return { ...numeric, ...Object.fromEntries(['minimum', 'maximum', 'normal_low', 'normal_high'].map(key => [key, Number(props[key])])) };
      }
      return numeric;
    }),
  };
}

export function projectScreens(project) {
  return [{ id: 'overview', title: project.title, columns: project.columns, update_ms: project.update_ms || 500, popup: false, controls: project.controls }, ...(project.screens || [])];
}

export function scopedScreen(project, id) {
  const screen = projectScreens(project).find(item => item.id === id) || projectScreens(project)[0];
  return { ...screen, controls: screen.controls.map(control => ({ ...control, id: screen.id === 'overview' ? control.id : `${screen.id}__${control.id}` })) };
}
