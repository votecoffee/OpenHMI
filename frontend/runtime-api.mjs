import { api, json } from './api.mjs';

export function writeControlValue(id, value, revision) {
  return api(`/api/controls/${encodeURIComponent(id)}/value`,
    json('PUT', { value, expected_revision: revision }));
}

export function activateControl(id, revision) {
  return api(`/api/controls/${encodeURIComponent(id)}/activate`,
    json('POST', { expected_revision: revision }));
}

export function renewSubscription(client, screens, previewRoot, sequence, keepalive = false) {
  return api('/api/subscriptions', {
    ...json('POST', { client, screens, preview_root: previewRoot, sequence }), keepalive,
  });
}

export const tagSnapshotPath = (statusOnly = false) => statusOnly ? '/api/tags?status_only=true' : '/api/tags';
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function requireTagSnapshot(tags, statusOnly = false) {
  const { values = statusOnly ? {} : null, samples = {},
    connections = statusOnly ? null : [], plc_hold: plcHold = statusOnly ? null : false } = tags ?? {};
  if (!isRecord(values) || !isRecord(samples) || typeof plcHold !== 'boolean'
    || !Array.isArray(connections) || connections.some(route =>
      typeof route?.id !== 'string' || typeof route.connected !== 'boolean')) {
    throw new Error('Invalid tag status response');
  }
  return { values, samples, connections, plcHold };
}
