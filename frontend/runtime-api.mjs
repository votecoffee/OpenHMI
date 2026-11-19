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
