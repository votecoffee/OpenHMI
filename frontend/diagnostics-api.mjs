import { readRuntimeSnapshot } from './api.mjs';

export function diagnosticsPath(criteria = {}, offset = 0, { limit = null } = {}) {
  const params = new URLSearchParams({ ...criteria, offset });
  if (limit !== null) params.set('limit', limit);
  return '/api/diagnostics?' + params;
}

export const diagnosticsExportPath = (criteria = {}) => '/api/diagnostics.json?' + new URLSearchParams(criteria);
export const readDiagnostics = (criteria, offset, options) => readRuntimeSnapshot(diagnosticsPath(criteria, offset, options));

export function isDiagnosticsSnapshot(data, offset) {
  if (!Number.isSafeInteger(offset) || offset < 0 || data?.offset !== offset || !Number.isSafeInteger(data.total_tags) || data.total_tags < 0
    || typeof data.plc_hold !== 'boolean' || (data.next_offset !== null
      && (!Number.isSafeInteger(data.next_offset) || data.next_offset <= offset))) return false;
  const textFields = (row, ...fields) => row != null && fields.every(field => typeof row[field] === 'string');
  const optionalText = value => value == null || typeof value === 'string';
  const optionalNumber = value => value == null || Number.isFinite(value);
  const names = new Set();
  const uniqueName = name => {
    if (names.has(name)) return false;
    names.add(name);
    return true;
  };
  return Array.isArray(data.tags) && data.tags.length <= Math.max(0, data.total_tags - offset)
    && typeof data.truncated === 'boolean' && data.truncated === (data.next_offset !== null)
    && (data.next_offset === null ? offset + data.tags.length >= data.total_tags
      : data.tags.length > 0 && data.next_offset === offset + data.tags.length && data.next_offset < data.total_tags)
    && data.tags.every(tag => textFields(tag, 'name', 'address', 'type', 'quality') && uniqueName(tag.name)
      && optionalText(tag.connection) && optionalText(tag.timestamp) && optionalText(tag.error) && optionalNumber(tag.age_seconds))
    && Array.isArray(data.workers) && data.workers.every(worker => textFields(worker, 'id', 'state')
      && Number.isSafeInteger(worker.failures) && optionalText(worker.last_success_at) && optionalText(worker.last_error_type)
      && optionalNumber(worker.retry_in_seconds) && (worker.state !== 'overdue' || Number.isFinite(worker.running_seconds)))
    && Array.isArray(data.connections) && data.connections.every(route => textFields(route, 'id', 'name', 'path', 'state')
      && optionalText(route.error) && optionalNumber(route.scan_age_seconds) && [route.read_calls, route.tags_read, route.route_failures].every(Number.isSafeInteger)
      && Array.isArray(route.groups) && route.groups.every(group => Number.isFinite(group?.rate_ms)
        && Array.isArray(group.addresses) && group.addresses.every(address => typeof address === 'string'))
      && route.timings && typeof route.timings === 'object' && !Array.isArray(route.timings)
      && Object.values(route.timings).every(timing => timing && ['last_ms', 'p50_ms', 'p95_ms', 'p99_ms', 'count']
        .every(field => Number.isFinite(timing[field]))));
}
