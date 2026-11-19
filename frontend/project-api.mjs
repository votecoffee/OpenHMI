import { api, json } from './api.mjs';

export function saveProjectDraft(project, revision) {
  return api('/api/project/draft', json('PUT', { expected_revision: revision, project }));
}

export function applyLiveProject(revision, reason = 'Live apply') {
  return api('/api/project/apply', json('POST', {
    expected_revision: revision, reason: reason.trim() || 'Live apply',
  }));
}
