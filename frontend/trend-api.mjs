import { api, json } from './api.mjs';

export const trendCapturePath = id => '/api/trends/' + encodeURIComponent(id);

export function sendCaptureCommand(id, action, captureId) {
  return api(trendCapturePath(id), json('POST', { action, capture_id: captureId }));
}

export function captureHistoryPath(identifier, { seconds = 60, end = null } = {}) {
  const params = new URLSearchParams({ seconds, ...(end === null ? {} : { end }) });
  return `/api/trend-captures/${identifier}?${params}`;
}

export const captureCsvPath = identifier => `/api/trend-captures/${identifier}/csv`;
