export const controlTypes = {
  numeric: 'NumericDisplay', indicator: 'Indicator', button: 'ActionButton',
  analog: 'AnalogRange', alarm: 'AlarmIndicator',
  recipe: 'SelectedRecipe',
  input: 'NumericInput',
  faceplate: 'Faceplate', trend: 'Trend',
};
const kinds = Object.fromEntries(Object.entries(controlTypes).map(([kind, type]) => [type, kind]));

export function toEditor(project) {
  return {
    root: { props: { title: project.title, columns: project.columns, update_ms: project.update_ms || 500, screen_id: project.id || 'overview' } },
    content: project.controls.map(({ kind, ...props }) => ({ type: controlTypes[kind], props })),
  };
}

export function toProject(data, settings = {}) {
  return {
    ...settings,
    schema_version: 1, title: data.root.props.title, columns: Number(data.root.props.columns), update_ms: Number(data.root.props.update_ms || 500),
    controls: data.content.map(({ type, props }) => {
      const base = { kind: kinds[type], id: props.id, label: props.label, visible_tag: props.visible_tag || '', enabled_tag: props.enabled_tag || '', color_tag: props.color_tag || '', active_color: props.active_color || '#002878' };
      if (type === 'Faceplate') return { ...base, template: props.template, root_tag: props.root_tag };
      if (type === 'Trend') return { ...base, tags: props.tags || ['TankLevel'], seconds: Number(props.seconds || 300) };
      if (type === 'SelectedRecipe') return base;
      if (type === 'ActionButton') return { ...base, action: props.action || '', mode: props.mode || 'python', target: props.target || '', value: props.value ?? false, screen: props.screen || 'overview', security_groups: props.security_groups || [] };
      if (type === 'AlarmIndicator') return { ...base, tag: props.tag, priority: Number(props.priority) };
      if (type === 'Indicator') return { ...base, tag: props.tag, on_text: props.on_text ?? 'ON', off_text: props.off_text ?? 'OFF' };
      const numeric = { ...base, tag: props.tag, unit: props.unit, decimals: Number(props.decimals) };
      if (type === 'NumericInput') return { ...numeric, minimum: Number(props.minimum), maximum: Number(props.maximum), security_groups: props.security_groups || [] };
      if (type === 'AnalogRange') {
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
