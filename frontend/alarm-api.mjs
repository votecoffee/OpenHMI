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

export const alarmStates = ['outstanding', 'active', 'unacknowledged', 'returned', 'acknowledged', 'retired', 'all'];
export const alarmShelvingFilters = ['unshelved', 'shelved', 'all'];
export const alarmEvents = ['active', 'returned', 'acknowledged', 'quality_bad', 'quality_recovered', 'configuration_changed', 'operator_note', 'shelved', 'shelf_restored', 'shelf_expired', 'shelf_invalidated'];

function alarmParameters(filters, before, history = false, event = '') {
  const query = new URLSearchParams({ priority: filters.priority, search: filters.search, state: history ? 'all' : filters.state });
  if (!history) query.set('shelving', filters.shelving);
  for (const field of ['start', 'end']) if (filters[field]) query.set(field, new Date(filters[field]).toISOString());
  if (before) query.set('before_id', before);
  if (event) query.set('event', event);
  return query;
}

export function alarmOccurrencesPath(filters, before = null, { limit = null } = {}) {
  const query = alarmParameters(filters, before);
  if (limit !== null) query.set('limit', limit);
  return '/api/alarms/occurrences?' + query;
}

export function alarmEventsPath(filters, before = null, event = '', { limit = null } = {}) {
  const query = alarmParameters(filters, before, true, event);
  if (limit !== null) query.set('limit', limit);
  return '/api/alarms/events?' + query;
}

export const alarmEventsCsvPath = (filters, event = '') => '/api/alarms/events.csv?' + alarmParameters(filters, null, true, event);
export const alarmDetailPath = identifier => '/api/alarms/occurrences/' + encodeURIComponent(identifier);

export function alarmNotesPath(identifier, before = null, { limit = null } = {}) {
  const query = new URLSearchParams();
  if (before) query.set('before_id', before);
  if (limit !== null) query.set('limit', limit);
  return alarmDetailPath(identifier) + '/notes' + (query.size ? '?' + query : '');
}

export function saveAlarmNote(identifier, comment) {
  return api(alarmNotesPath(identifier), json('POST', { comment }));
}

export function shelveAlarm(identifier, duration, reason) {
  return api(alarmDetailPath(identifier) + '/shelve', json('POST', { duration_seconds: Number(duration), reason }));
}

export function restoreAlarm(alarmId, expectedOperationId, reason) {
  return api('/api/alarms/shelves/' + encodeURIComponent(alarmId) + '/restore',
    json('POST', { expected_operation_id: expectedOperationId, reason }));
}
