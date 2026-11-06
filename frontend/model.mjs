export const controlTypes = {
  numeric: 'NumericDisplay', indicator: 'Indicator', button: 'ActionButton',
  analog: 'AnalogRange', tank: 'TankLevel', gauge: 'RadialGauge', bar: 'BarGraph', pie: 'PieChart', xy: 'XYChart', radar: 'RadarChart', alarm: 'AlarmIndicator',
  recipe: 'SelectedRecipe', label: 'StaticLabel', symbol: 'ScreenSymbol', sparkline: 'Sparkline',
  input: 'NumericInput', slider: 'Slider', date_time: 'DateTimeInput', progress: 'ProgressBar',
  text_input: 'TextInput', text_area: 'TextArea', barcode_input: 'BarcodeInput', current_user: 'CurrentUser',
  dropdown: 'Dropdown', radio_group: 'RadioGroup', checkbox: 'Checkbox', toggle_switch: 'ToggleSwitch',
  faceplate: 'Faceplate', trend: 'Trend', text: 'TextDisplay', date_time_display: 'DateTimeDisplay', duration: 'DurationDisplay', web_browser: 'WebBrowser',
  multi_state: 'MultiState', mode_selector: 'ModeSelector', permissives: 'PermissiveList', stack_light: 'StackLight',
};
const kinds = Object.fromEntries(Object.entries(controlTypes).map(([kind, type]) => [type, kind]));

export function toEditor(project) {
  return {
    root: { props: { title: project.title, columns: project.columns, update_ms: project.update_ms || 500, screen_id: project.id || 'overview', layout: project.layout ?? null } },
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
    schema_version: 1, layout: data.root.props.layout ?? null, title: data.root.props.title, columns: Number(data.root.props.columns), update_ms: Number(data.root.props.update_ms || 500),
    controls: data.content.map(({ type, props }) => {
      const base = { kind: kinds[type], id: props.id, label: props.label, visible_tag: props.visible_tag || '', enabled_tag: props.enabled_tag || '', color_tag: props.color_tag || '', active_color: props.active_color || '#002878' };
      if (type === 'Faceplate') return { ...base, template: props.template, root_tag: props.root_tag };
      if (type === 'Trend') return { ...base, tags: props.pens?.tags ?? props.tags ?? ['TankLevel'],
        series: props.pens?.series ?? props.series ?? {}, seconds: Number(props.seconds ?? 300), recording: props.recording ?? null };
      if (type === 'WebBrowser') return { ...base, scheme: props.scheme || 'https', hosts: props.hosts || '',
        port: props.port === '' || props.port == null ? null : Number(props.port), path: props.path ?? '/',
        address_tag: props.address_tag || '', refresh_tag: props.refresh_tag || '' };
      if (type === 'XYChart') return { ...base, series: props.series, decimals: Number(props.decimals),
        x_minimum: Number(props.x_minimum), x_maximum: Number(props.x_maximum), x_unit: props.x_unit,
        y_minimum: Number(props.y_minimum), y_maximum: Number(props.y_maximum), y_unit: props.y_unit };
      if (type === 'PieChart') return { ...base, series: props.series, unit: props.unit };
      if (type === 'RadarChart') return { ...base, series: props.series };
      if (type === 'BarGraph') return { ...base, series: props.series, unit: props.unit,
        minimum: Number(props.minimum), maximum: Number(props.maximum) };
      if (type === 'SelectedRecipe' || type === 'CurrentUser') return base;
      if (type === 'MultiState') return { ...base, tag: props.tag, states: props.states };
      if (type === 'ModeSelector') return { ...base, tag: props.tag, confirmed_tag: props.confirmed_tag,
        states: props.states, presentation: props.presentation || 'dropdown', security_groups: props.security_groups || [] };
      if (type === 'StackLight') return { ...base, lamps: props.lamps, orientation: props.orientation };
      if (type === 'PermissiveList') return { ...base, checks: props.checks };
      if (type === 'StaticLabel') return { ...base, font_size: Number(props.font_size), alignment: props.alignment, weight: props.weight };
      if (type === 'ScreenSymbol') return { ...base, symbol: props.symbol, size: Number(props.size), rotation: Number(props.rotation) };
      if (type === 'DateTimeInput') return { ...base, tag: props.tag,
        minimum: props.minimum, maximum: props.maximum, minimum_tag: props.minimum_tag || '',
        maximum_tag: props.maximum_tag || '', security_groups: props.security_groups || [] };
      if (type === 'TextDisplay' || type === 'DateTimeDisplay') return { ...base, tag: props.tag };
      if (type === 'DurationDisplay') return { ...base, tag: props.tag, source_unit: props.source_unit, decimals: Number(props.decimals) };
      if (type === 'Dropdown' || type === 'RadioGroup') return { ...base, tag: props.tag, options: props.options, security_groups: props.security_groups || [] };
      if (type === 'Checkbox' || type === 'ToggleSwitch') return { ...base, tag: props.tag, security_groups: props.security_groups || [] };
      if (['TextInput', 'TextArea', 'BarcodeInput'].includes(type)) return { ...base, tag: props.tag, min_length: Number(props.min_length ?? 0), max_length: Number(props.max_length ?? 82), min_length_tag: props.min_length_tag || '', max_length_tag: props.max_length_tag || '', security_groups: props.security_groups || [] };
      if (type === 'ActionButton') return { ...base, action: props.action || '', mode: props.mode || 'python', command: props.command || '', target: props.target || '', value: props.value ?? false, screen: props.screen || 'overview', security_groups: props.security_groups || [] };
      if (type === 'AlarmIndicator') return { ...base, tag: props.tag, priority: Number(props.priority) };
      if (type === 'Indicator') return { ...base, tag: props.tag, on_text: props.on_text ?? 'ON', off_text: props.off_text ?? 'OFF' };
      const numeric = { ...base, tag: props.tag, unit: props.unit, decimals: Number(props.decimals) };
      if (type === 'Sparkline') return { ...numeric, seconds: Number(props.seconds ?? 60) };
      if (type === 'ProgressBar') return { ...numeric, minimum: Number(props.minimum), maximum: Number(props.maximum) };
      if (type === 'NumericInput' || type === 'Slider') return { ...numeric, minimum: Number(props.minimum), maximum: Number(props.maximum), minimum_tag: props.minimum_tag || '', maximum_tag: props.maximum_tag || '', security_groups: props.security_groups || [] };
      if (['AnalogRange', 'TankLevel', 'RadialGauge'].includes(type)) {
        return { ...numeric, ...Object.fromEntries(['minimum', 'maximum', 'normal_low', 'normal_high'].map(key => [key, Number(props[key])])) };
      }
      return numeric;
    }),
  };
}

export function projectScreens(project) {
  return [{ id: 'overview', title: project.title, columns: project.columns, update_ms: project.update_ms || 500, popup: false, layout: project.layout, controls: project.controls }, ...(project.screens || [])];
}

export function scopedScreen(project, id) {
  const screen = projectScreens(project).find(item => item.id === id) || projectScreens(project)[0];
  if (screen.id === 'overview') return screen;
  const scoped = id => `${screen.id}__${id}`;
  const layout = screen.layout && { ...screen.layout,
    boxes: Object.fromEntries(Object.entries(screen.layout.boxes).map(([id, box]) => [scoped(id), box])),
    containers: Object.fromEntries(Object.entries(screen.layout.containers)
      .map(([id, container]) => [id, { ...container, members: container.members.map(scoped) }])),
  };
  return { ...screen, layout, controls: screen.controls.map(control => ({ ...control, id: scoped(control.id) })) };
}
