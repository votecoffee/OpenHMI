let projectInstance = null;
export function projectRequestHeaders() {
  return projectInstance ? { 'X-OpenHMI-Project': projectInstance } : {};
}

const instanceId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
function projectReadError(changed = false) {
  const error = new Error(changed ? 'A different project is open. Reload to continue' : 'Project data identity could not be confirmed');
  error.project_context = true;
  error.project_changed = changed;
  return error;
}

export function readRuntimeSnapshot(path) {
  return api(path, { projectRead: path === '/api/project/active' ? 'active' : 'same' });
}

export async function api(path, options = {}) {
  const { projectRead, ...requestOptions } = options;
  if (projectRead && (!['same', 'active'].includes(projectRead) || (requestOptions.method ?? 'GET').toUpperCase() !== 'GET')) {
    throw new Error('Project snapshot identity checks require a supported GET read mode');
  }
  const expected = projectInstance;
  if (projectRead && !instanceId(expected)) throw projectReadError();
  const headers = { ...requestOptions.headers, ...projectRequestHeaders() };
  const response = await fetch(path, { signal: AbortSignal.timeout(5000), ...requestOptions, headers });
  if (!response.ok) {
    const { detail } = (await response.json().catch(() => null)) ?? {};
    const message = Array.isArray(detail) ? detail.filter(item => Array.isArray(item?.loc) && typeof item.msg === 'string')
      .map(item => `${item.loc.join('.')}: ${item.msg}`).join('; ') : detail;
    const error = new Error(typeof message === 'string' && message ? message : `HTTP ${response.status}`);
    error.status = response.status;
    error.conflict = response.status === 409;
    error.operation_id = response.headers.get('X-OpenHMI-Operation-ID');
    error.audit_status = response.headers.get('X-OpenHMI-Audit-Status');
    throw error;
  }
  const source = response.headers.get('X-OpenHMI-Project');
  if (projectRead && (!instanceId(source) || (projectRead === 'same' && source !== expected))) {
    await response.body?.cancel().catch(() => {});
    throw projectReadError(instanceId(source) && source !== expected);
  }
  let data;
  try {
    data = await response.json();
    if (projectRead === 'active' && data?.project_instance !== source) throw projectReadError();
    if (response.headers.has('X-OpenHMI-Operation-ID')) {
      data.operation_id = response.headers.get('X-OpenHMI-Operation-ID');
      data.audit_status = response.headers.get('X-OpenHMI-Audit-Status');
    }
  } catch (error) {
    if (response.headers.has('X-OpenHMI-Operation-ID')) {
      error.operation_id = response.headers.get('X-OpenHMI-Operation-ID');
      error.audit_status = response.headers.get('X-OpenHMI-Audit-Status');
    }
    throw error;
  }
  if (!projectInstance && path === '/api/project') projectInstance = data.project_instance || response.headers.get('X-OpenHMI-Project');
  return data;
}

export function uploadProjectImage(file) {
  return api('/api/canvas-images?' + new URLSearchParams({ name: file.name }), {
    method: 'POST', body: file, signal: AbortSignal.timeout(15000),
  });
}

export function json(method, body) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
