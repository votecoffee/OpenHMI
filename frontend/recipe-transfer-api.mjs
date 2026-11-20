import { api, json } from './api.mjs';

export function recipeTransferPaths(filters = {}, before = null, verifiedProfile = null, { limit = 25 } = {}) {
  const parameters = new URLSearchParams({ limit: String(limit) });
  if (before) parameters.set('before_id', before);
  if (filters.profile) parameters.set('profile_id', filters.profile);
  if (filters.production) parameters.set('production_approved', filters.production);
  const historyQuery = parameters.toString();
  if (verifiedProfile !== null) parameters.set('verified_profile', verifiedProfile);
  return { historyQuery, endpoint: '/api/recipe-transfers?' + parameters };
}

export function recipeTransferPath(identifier, { download = false } = {}) {
  return '/api/recipe-transfers/' + encodeURIComponent(identifier) + (download ? '?download=true' : '');
}

export function dispatchRecipeTransfer(profileId, revisionId, expectedRevisionVersion, expectedProjectRevision, reason) {
  return api('/api/recipe-transfers/' + encodeURIComponent(profileId) + '/dispatch', json('POST', {
    revision_id: revisionId, expected_revision_version: expectedRevisionVersion,
    expected_project_revision: expectedProjectRevision, reason,
  }));
}
