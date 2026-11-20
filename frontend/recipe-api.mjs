import { api, json } from './api.mjs';

export function validatedRecipeContent(content) {
  return { ...content, parameters: content.parameters.map(parameter => {
    const numeric = ['number', 'integer'].includes(parameter.type);
    if (numeric && !String(parameter.value).trim()) throw new Error(`Enter a value for ${parameter.label}`);
    return { ...parameter, value: numeric ? Number(parameter.value) : parameter.value,
      minimum: parameter.minimum == null || parameter.minimum === '' ? null : Number(parameter.minimum),
      maximum: parameter.maximum == null || parameter.maximum === '' ? null : Number(parameter.maximum) };
  }) };
}

export function createRecipe(code, content, reason) {
  return api('/api/recipes', json('POST', { code, content, reason }));
}

export function saveRecipeRevision(recipeId, expectedLatestRevision, parentRevision, content, reason) {
  return api(`/api/recipes/${recipeId}/revisions`, json('POST', {
    expected_latest_revision: expectedLatestRevision, parent_revision: parentRevision, content, reason,
  }));
}

export function transitionRecipeRevision(revisionId, action, expectedVersion, reason) {
  return api(`/api/recipe-revisions/${revisionId}/transition`, json('POST', { action, expected_version: expectedVersion, reason }));
}

export function selectRecipeRevision(revisionId, expectedRevisionVersion, expectedSelectionVersion, reason) {
  return api('/api/recipes/select', json('POST', { revision_id: revisionId, expected_revision_version: expectedRevisionVersion,
    expected_selection_version: expectedSelectionVersion, reason }));
}
