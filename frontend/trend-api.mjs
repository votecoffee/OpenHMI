import { api, json } from './api.mjs';

export const trendCapturePath = id => '/api/trends/' + encodeURIComponent(id);

export function sendCaptureCommand(id, action, captureId) {
  return api(trendCapturePath(id), json('POST', { action, capture_id: captureId }));
}
