// Same-project synthetic fixtures need the header supplied by the real server.
// Missing/foreign identity tests must use raw route.fulfill instead of this helper.
const runtimePaths = new Set(['/api/tags', '/api/alarms', '/api/recipes/selected', '/api/security/session', '/api/project/active']);

export function fulfillProjectRead(route, options) {
  const expected = route.request().headers()['x-openhmi-project'];
  if (!expected || !runtimePaths.has(new URL(route.request().url()).pathname)) return route.fulfill(options);
  const headers = new Headers(options.response?.headers() ?? {});
  for (const [name, value] of Object.entries(options.headers ?? {})) headers.set(name, value);
  if (!headers.has('X-OpenHMI-Project')) headers.set('X-OpenHMI-Project', expected);
  return route.fulfill({ ...options, headers: Object.fromEntries(headers) });
}
