let projectInstance = null;
export async function api(path, options = {}) {
  const headers = { ...options.headers, ...(projectInstance ? { 'X-OpenHMI-Project': projectInstance } : {}) };
  const response = await fetch(path, { signal: AbortSignal.timeout(5000), ...options, headers });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => `${item.loc.join('.')}: ${item.msg}`).join('; ') : data.detail;
    const error = new Error(detail || `HTTP ${response.status}`);
    error.conflict = response.status === 409;
    throw error;
  }
  if (!projectInstance && path === '/api/project') projectInstance = data.project_instance || response.headers.get('X-OpenHMI-Project');
  return data;
}

export function json(method, body) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
