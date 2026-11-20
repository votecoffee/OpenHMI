import { api, json } from './api.mjs';

export function acknowledgeAlarms(id, comment, selected = null) {
  const path = selected !== null ? '/api/alarms/acknowledge-selected'
    : id == null ? '/api/alarms/acknowledge-all' : `/api/alarms/${id}/acknowledge`;
  return api(path, json('POST', { comment, ...(selected !== null ? { occurrence_ids: selected } : {}) }));
}

export const alarmSnapshotPath = '/api/alarms';
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function isAlarmSnapshot(alarms) {
  if (!isRecord(alarms)) return false;
  const { states, outstanding, annunciated_outstanding: annunciated = outstanding,
    active_count, unacknowledged_count, annunciated_active_count = active_count,
    annunciated_unacknowledged_count = unacknowledged_count, shelved_count = 0,
    sampled_revision = null, evaluation_stale = false } = alarms;
  const counts = [active_count, unacknowledged_count, annunciated_active_count,
    annunciated_unacknowledged_count, shelved_count];
  return counts.every(count => Number.isSafeInteger(count) && count >= 0)
    && (sampled_revision === null || Number.isSafeInteger(sampled_revision))
    && typeof evaluation_stale === 'boolean'
    && isRecord(states) && Object.values(states).every(state => ['good', 'bad'].includes(state?.quality))
    && Array.isArray(outstanding) && Array.isArray(annunciated)
    && annunciated.every(alarm => isRecord(alarm) && [1, 2, 3, 4].includes(alarm.priority)
      && typeof alarm.message === 'string'
      && (alarm.occurrence_id === undefined || Number.isSafeInteger(alarm.occurrence_id))
      && (alarm.messages === undefined || (isRecord(alarm.messages)
        && Object.values(alarm.messages).every(message => typeof message === 'string'))));
}
