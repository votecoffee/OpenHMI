import { api, json } from './api.mjs';
import { controlTypes } from './model.mjs';

export function saveProjectDraft(project, revision) {
  return api('/api/project/draft', json('PUT', { expected_revision: revision, project }));
}

export function applyLiveProject(revision, reason = 'Live apply') {
  return api('/api/project/apply', json('POST', {
    expected_revision: revision, reason: reason.trim() || 'Live apply',
  }));
}

export const appliedProjectPath = '/api/project/active';
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);

function hasScreenControls(controls) {
  return Array.isArray(controls) && controls.every(control => isRecord(control)
    && typeof control.id === 'string' && typeof control.label === 'string'
    && typeof control.kind === 'string' && Object.hasOwn(controlTypes, control.kind));
}

function hasScreenLayout(screen) {
  if (!isRecord(screen) || typeof screen.title !== 'string' || !hasScreenControls(screen.controls)) return false;
  const { columns = 2, update_ms: interval = 500, layout } = screen;
  if (![1, 2, 3].includes(columns) || !Number.isInteger(interval) || interval < 100 || interval > 60000) return false;
  if (layout == null) return true;
  return isRecord(layout) && isRecord(layout.boxes) && isRecord(layout.containers)
    && Object.values(layout.boxes).every(isRecord)
    && Object.values(layout.containers).every(container => isRecord(container) && Array.isArray(container.members))
    && (layout.decorations === undefined || (isRecord(layout.decorations) && Object.values(layout.decorations).every(isRecord)));
}

export function isAppliedProjectSnapshot(snapshot) {
  if (!isRecord(snapshot)) return false;
  const { revision, project_instance: instance, project } = snapshot;
  if (!Number.isSafeInteger(revision) || revision < 1 || typeof instance !== 'string'
    || !/^[a-f0-9]{32}$/.test(instance) || !hasScreenLayout(project)) return false;
  const { screens = [], faceplates = [] } = project;
  const collections = ['connections', 'tags', 'commands', 'recipe_transfers', 'languages', 'alarms'];
  return Array.isArray(screens) && screens.every(screen => hasScreenLayout(screen) && typeof screen.id === 'string')
    && Array.isArray(faceplates) && faceplates.every(template => isRecord(template) && hasScreenControls(template.controls))
    && collections.every(key => project[key] === undefined || (Array.isArray(project[key]) && project[key].every(isRecord)));
}
