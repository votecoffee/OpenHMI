import { api } from './api.mjs';

function activityParams(filters, before) {
  const query = new URLSearchParams();
  for (const key of ['actor', 'status', 'search']) if (filters[key]) query.set(key, filters[key]);
  for (const key of ['start', 'end']) if (filters[key]) query.set(key, new Date(filters[key]).toISOString());
  if (before) query.set('before_id', before);
  return query;
}

export function activityHistoryPath(filters = {}, before = null, { limit = null } = {}) {
  const params = activityParams(filters, before);
  if (limit !== null) params.set('limit', limit);
  return '/api/activity?' + params;
}

export const activityCsvPath = (filters = {}) => '/api/activity.csv?' + activityParams(filters);
export const readActivity = (filters, before, options) => api(activityHistoryPath(filters, before, options));

export const activityOutcomes = ['pending', 'succeeded', 'denied', 'rejected', 'uncertain', 'interrupted'];

export function isActivityRecord(item) {
  const isObject = value => value != null && typeof value === 'object' && !Array.isArray(value);
  const optionalText = value => value == null || typeof value === 'string';
  if (!isObject(item) || !Number.isSafeInteger(item.id) || item.id <= 0 || !activityOutcomes.includes(item.status) || !isObject(item.context)
    || !['operation_id', 'started_at', 'actor', 'provider', 'operation', 'entity', 'phase']
      .every(key => typeof item[key] === 'string')) return false;
  const { context, outcome } = item;
  return Array.isArray(item.groups) && item.groups.every(group => typeof group === 'string')
    && [item.finished_at, item.error, context.tag, context.target, context.before?.quality, context.before?.timestamp]
      .every(optionalText)
    && (outcome === null || (isObject(outcome) && optionalText(outcome.verification)
      && optionalText(outcome.observed_at) && (outcome.count == null || Number.isSafeInteger(outcome.count))));
}

export function isActivityPage(page) {
  const operations = new Set();
  return Array.isArray(page?.items) && page.items.length <= 1000
    && page.items.every((item, index) => {
      if (!isActivityRecord(item) || operations.has(item.operation_id)
        || (index > 0 && page.items[index - 1].id <= item.id)) return false;
      operations.add(item.operation_id);
      return true;
    }) && typeof page.has_more === 'boolean'
    && (page.has_more ? page.items.length > 0 && page.next_before_id === page.items.at(-1).id : page.next_before_id === null)
    && [page.pending_finalizations, page.retention_days, page.max_resolved_rows]
      .every(value => Number.isSafeInteger(value) && value >= 0);
}
