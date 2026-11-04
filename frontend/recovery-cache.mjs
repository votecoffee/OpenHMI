function ordered(value) {
  if (Array.isArray(value)) return value.map(ordered);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])]));
  return value;
}

export function retainCandidate(key, candidate, blocked) {
  if (!blocked && JSON.stringify(ordered(candidate.base)) === JSON.stringify(ordered(candidate.local))) localStorage.removeItem(key);
  else localStorage.setItem(key, JSON.stringify({ format: 'OpenHMI-recovery', version: 1, ...candidate }));
}

export function readCandidate(key) {
  try {
    const item = JSON.parse(localStorage.getItem(key) || 'null');
    return item?.format === 'OpenHMI-recovery' && item.version === 1 && Array.isArray(item.local?.controls) && Array.isArray(item.base?.controls) && item.base_revision >= 1 ? item : null;
  } catch { return null; }
}

export function editorIdentity() {
  try {
    let id = sessionStorage.getItem('openhmi-editor-id');
    if (!id) { id = crypto.randomUUID(); sessionStorage.setItem('openhmi-editor-id', id); }
    return id;
  } catch { return crypto.randomUUID(); }
}

export function recoveryPrefix(projectId, user) {
  return `openhmi-recovery:${projectId}:${user?.provider || 'simulation'}:${user?.name || 'simulation'}:`;
}
