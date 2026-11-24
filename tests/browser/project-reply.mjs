// Same-project synthetic fixtures need the header supplied by the real server.
// Missing/foreign identity tests must use raw route.fulfill instead of this helper.
const runtimePaths = new Set(['/api/tags', '/api/alarms', '/api/recipes/selected', '/api/security/session', '/api/project/active']);

export function fulfillProjectRead(route, options) {
  const expected = route.request().headers()['x-openhmi-project'];
  const path = new URL(route.request().url()).pathname;
  const alarmRead = route.request().method() === 'GET'
    && /^\/api\/alarms\/(occurrences(?:\/[1-9]\d*(?:\/notes)?)?|events|shelves)$/.test(path);
  const commandRead = route.request().method() === 'GET' && /^\/api\/commands(?:\/[1-9]\d*)?$/.test(path);
  if (!expected || !(runtimePaths.has(path) || alarmRead || commandRead)) return route.fulfill(options);
  const headers = new Headers(options.response?.headers() ?? {});
  for (const [name, value] of Object.entries(options.headers ?? {})) headers.set(name, value);
  if (options.json !== undefined || options.body !== undefined) headers.delete('Content-Length');
  if (!headers.has('X-OpenHMI-Project')) headers.set('X-OpenHMI-Project', expected);
  return route.fulfill({ ...options, headers: Object.fromEntries(headers) });
}
