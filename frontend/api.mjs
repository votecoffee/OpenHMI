let projectInstance = null;
export async function api(path, options = {}) {
  const headers = { ...options.headers, ...(projectInstance ? { 'X-OpenHMI-Project': projectInstance } : {}) };
  const response = await fetch(path, { signal: AbortSignal.timeout(5000), ...options, headers });
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
  const data = await response.json();
  if (response.headers.has('X-OpenHMI-Operation-ID')) {
    data.operation_id = response.headers.get('X-OpenHMI-Operation-ID');
    data.audit_status = response.headers.get('X-OpenHMI-Audit-Status');
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
