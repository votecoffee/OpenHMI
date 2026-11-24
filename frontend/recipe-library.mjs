import { readRuntimeSnapshot } from './api.mjs';

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const positiveId = value => Number.isSafeInteger(value) && value > 0;
const optionalText = value => value == null || typeof value === 'string';
const optionalId = value => value == null || positiveId(value);
const operations = ['editing', 'approval', 'loading'];
const statuses = ['draft', 'in_review', 'approved', 'rejected', 'withdrawn', 'superseded'];

function isContent(content) {
  const names = new Set();
  return record(content) && typeof content.title === 'string' && optionalText(content.description)
    && (content.image_id == null || content.image_id === '' || (typeof content.image_id === 'string' && /^[a-f0-9]{64}$/.test(content.image_id)))
    && Array.isArray(content.parameters) && content.parameters.every(parameter => {
      if (!record(parameter) || typeof parameter.name !== 'string' || names.has(parameter.name)
        || typeof parameter.label !== 'string' || !optionalText(parameter.unit)) return false;
      names.add(parameter.name);
      const value = parameter.value;
      const valid = parameter.type === 'number' ? Number.isFinite(value) : parameter.type === 'integer' ? Number.isSafeInteger(value)
        : parameter.type === 'boolean' ? typeof value === 'boolean' : parameter.type === 'text' && typeof value === 'string';
      return valid && [parameter.minimum, parameter.maximum].every(limit => limit == null || Number.isFinite(limit));
    });
}

function isRevision(item) {
  return record(item) && [item.id, item.recipe_id, item.number, item.version].every(positiveId)
    && typeof item.code === 'string' && statuses.includes(item.status) && isContent(item.content)
    && [item.author, item.approved_by, item.approved_at].every(optionalText);
}

function isAudit(item) {
  return record(item) && positiveId(item.id) && optionalId(item.recipe_id) && optionalId(item.revision_id)
    && typeof item.timestamp === 'string' && typeof item.operation === 'string' && optionalText(item.actor)
    && record(item.details) && optionalText(item.details.reason)
    && (item.details.changes == null || (Array.isArray(item.details.changes)
      && item.details.changes.every(change => record(change) && typeof change.field === 'string')));
}

const descending = (items, valid) => Array.isArray(items)
  && items.every((item, index) => valid(item) && (index === 0 || items[index - 1].id > item.id));

export function isRecipeLibrary(library) {
  const policy = library?.change_policy;
  return record(library) && descending(library.revisions, isRevision) && descending(library.audit, isAudit)
    && record(policy) && positiveId(policy.version) && record(policy.policy)
    && operations.every(operation => typeof policy.policy[operation + '_enabled'] === 'boolean'
      && optionalText(policy.policy[operation + '_permit_tag']))
    && record(library.gates) && operations.every(operation => record(library.gates[operation]))
    && Object.values(library.gates).every(gate => record(gate) && typeof gate.allowed === 'boolean' && optionalText(gate.permit_tag));
}

export async function readRecipeLibrary() {
  const library = await readRuntimeSnapshot('/api/recipes');
  if (!isRecipeLibrary(library)) throw new Error('Invalid recipe library response');
  return library;
}
