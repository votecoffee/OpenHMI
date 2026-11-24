import { api, json, readRuntimeSnapshot } from './api.mjs';

export const trendCapturePath = id => '/api/trends/' + encodeURIComponent(id);
export const readCaptureStatus = id => readRuntimeSnapshot(trendCapturePath(id));

export function sendCaptureCommand(id, action, captureId) {
  return api(trendCapturePath(id), json('POST', { action, capture_id: captureId }));
}

export function captureHistoryPath(identifier, { seconds = 60, end = null } = {}) {
  const params = new URLSearchParams({ seconds, ...(end === null ? {} : { end }) });
  return `/api/trend-captures/${identifier}?${params}`;
}

export const captureCsvPath = identifier => `/api/trend-captures/${identifier}/csv`;

export function isCaptureStatus(status) {
  const epoch = value => Number.isFinite(value) && Math.abs(value) <= 8.64e12;
  const optionalEpoch = value => value === null || epoch(value);
  const count = value => Number.isSafeInteger(value) && value >= 0;
  const ids = new Set();
  const unique = id => {
    if (ids.has(id)) return false;
    ids.add(id);
    return true;
  };
  return typeof status?.enabled === 'boolean' && (status.error == null || typeof status.error === 'string')
    && Array.isArray(status.captures) && status.captures.every(item => count(item?.id) && item.id > 0 && unique(item.id)
      && epoch(item.started) && optionalEpoch(item.stopped) && optionalEpoch(item.first) && optionalEpoch(item.last)
      && (item.reason == null || typeof item.reason === 'string')
      && [item.retained, item.max_samples, item.rolled_off].every(count)
      && item.max_samples > 0 && item.retained <= item.max_samples
      && Array.isArray(item.series) && item.series.every(pen => typeof pen?.tag === 'string'
        && ['number', 'boolean'].includes(pen.type)
        && (pen.decimals == null || (count(pen.decimals) && pen.decimals <= 8))
        && (pen.minimum == null || Number.isFinite(pen.minimum)) && (pen.maximum == null || Number.isFinite(pen.maximum))));
}
