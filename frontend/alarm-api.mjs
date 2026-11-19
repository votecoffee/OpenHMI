import { api, json } from './api.mjs';

export function acknowledgeAlarms(id, comment, selected = null) {
  const path = selected !== null ? '/api/alarms/acknowledge-selected'
    : id == null ? '/api/alarms/acknowledge-all' : `/api/alarms/${id}/acknowledge`;
  return api(path, json('POST', { comment, ...(selected !== null ? { occurrence_ids: selected } : {}) }));
}
