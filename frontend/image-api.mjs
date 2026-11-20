import { api } from './api.mjs';

export function projectImageListPath({ before = null, search = '', limit = null } = {}) {
  const params = new URLSearchParams();
  if (before) params.set('before', before);
  if (search) params.set('search', search);
  if (limit != null) params.set('limit', String(limit));
  return '/api/canvas-images' + (params.size ? '?' + params : '');
}

export function listProjectImages(options) {
  return api(projectImageListPath(options));
}

export function isProjectImagePage(page) {
  if (!page || Array.isArray(page) || !Array.isArray(page.items) || page.items.length > 32
    || !(page.next_before === null || (Number.isSafeInteger(page.next_before) && page.next_before > 0))
    || (!page.items.length && page.next_before !== null)) return false;
  const ids = new Set();
  return page.items.every(asset => {
    if (typeof asset?.id !== 'string' || !/^[a-f0-9]{64}$/.test(asset.id)
      || typeof asset.name !== 'string' || ids.has(asset.id)) return false;
    ids.add(asset.id);
    return true;
  });
}
