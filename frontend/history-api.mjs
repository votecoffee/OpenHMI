import { api } from './api.mjs';
import { captureHistoryPath } from './trend-api.mjs';

export function sparklineHistoryPath(tag, seconds) {
  return '/api/history?' + new URLSearchParams({ tags: tag, seconds, limit: 1000, trend_context: true });
}

export function trendReadPaths({ tags, seconds, end = null, captureId = null }) {
  const params = new URLSearchParams({ seconds, ...(end === null ? {} : { end }) });
  if (captureId === null) params.set('tags', tags);
  return {
    query: captureId !== null ? captureHistoryPath(captureId, { seconds, end })
      : tags ? `/api/history?${params}&trend_context=true` : '',
    csv: captureId === null && tags ? '/api/history.csv?' + params : '',
  };
}

export function historyTagsPath({ prefix = '', projectInstance, after = null, limit = null }) {
  const params = new URLSearchParams({ prefix, project_instance: projectInstance });
  if (after !== null) params.set('after', after);
  if (limit !== null) params.set('limit', limit);
  return '/api/history/tags?' + params;
}

export function recordedHistoryTags(options) {
  return api(historyTagsPath(options));
}

export function historyExportPath({ tags, seconds = 3600, start = null, end = null, complete = false, projectInstance }) {
  const params = new URLSearchParams({ tags });
  if (end !== null) params.set('end', String(end));
  if (start !== null) params.set('start', String(start));
  else params.set('seconds', String(seconds));
  if (complete) params.set('project_instance', projectInstance);
  return (complete ? '/api/history/full.csv?' : '/api/history.csv?') + params;
}

export function fetchHistoryCsv(path) {
  return fetch(path, { signal: AbortSignal.timeout(30000) });
}

export function isRecordedTagPage(page) {
  if (!Array.isArray(page?.items) || page.items.length > 100
    || !(page.next_after === null || (typeof page.next_after === 'string' && page.next_after.length > 0 && page.next_after.length <= 200))
    || (page.next_after !== null && page.items.at(-1)?.tag !== page.next_after)) return false;
  const tags = new Set();
  return page.items.every(item => {
    if (typeof item?.tag !== 'string' || !item.tag || item.tag.length > 200 || tags.has(item.tag)
      || typeof item.latest !== 'string' || !Number.isFinite(Date.parse(item.latest))) return false;
    tags.add(item.tag);
    return true;
  });
}
