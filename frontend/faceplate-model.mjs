// Resolve a template into the same tag bindings used by backend acquisition.
export function resolveFaceplateControl(control, { id, root_tag, puck, enabled_tag }) {
  const resolved = { ...control, id: `${id}__${control.id}`, puck, instance_enabled_tag: enabled_tag };
  for (const field of ['tag', 'target', 'visible_tag', 'enabled_tag', 'color_tag',
    'minimum_tag', 'maximum_tag', 'min_length_tag', 'max_length_tag', 'address_tag', 'refresh_tag', 'confirmed_tag', 'setpoint_tag', 'tolerance_tag']) {
    if (resolved[field]?.startsWith('$.')) resolved[field] = root_tag + resolved[field].slice(1);
  }
  for (const field of ['checks', 'lamps']) {
    if (resolved[field]) resolved[field] = resolved[field].map(row =>
      row.tag.startsWith('$.') ? { ...row, tag: root_tag + row.tag.slice(1) } : row);
  }
  if (resolved.tags) {
    const resolve = tag => tag.startsWith('$.') ? root_tag + tag.slice(1) : tag;
    resolved.tags = resolved.tags.map(resolve);
    resolved.series = Object.fromEntries(Object.entries(resolved.series || {}).map(([tag, settings]) => [resolve(tag), settings]));
    if (resolved.recording) resolved.recording = { ...resolved.recording,
      start_tag: resolve(resolved.recording.start_tag), stop_tag: resolve(resolved.recording.stop_tag) };
    resolved.pens = { tags: resolved.tags, series: resolved.series, root: root_tag };
  }
  if (Array.isArray(resolved.series)) {
    const fields = resolved.kind === 'xy' ? ['x_tag', 'y_tag'] : ['tag'];
    resolved.series = resolved.series.map(item => {
      const series = { ...item };
      for (const field of fields) if (series[field].startsWith('$.')) series[field] = root_tag + series[field].slice(1);
      return series;
    });
  }
  return resolved;
}
