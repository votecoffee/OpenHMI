export const recipeSelectionPath = '/api/recipes/selected';
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);

function isRecipeParameter(parameter) {
  if (!isRecord(parameter) || typeof parameter.name !== 'string'
    || typeof parameter.label !== 'string' || typeof parameter.unit !== 'string') return false;
  const { type, value } = parameter;
  switch (type) {
    case 'number': return Number.isFinite(value);
    case 'integer': return Number.isSafeInteger(value);
    case 'boolean': return typeof value === 'boolean';
    case 'text': return typeof value === 'string';
    default: return false;
  }
}

export function isRecipeSelection(selection) {
  if (!isRecord(selection) || !Number.isSafeInteger(selection.version) || selection.version < 1) return false;
  const { snapshot } = selection;
  if (snapshot === null) return true;
  if (!isRecord(snapshot)) return false;
  const { content, code, number, production_approved, loaded_by, loaded_at, approved_by } = snapshot;
  return typeof code === 'string' && Number.isSafeInteger(number) && number > 0
    && typeof production_approved === 'boolean' && typeof loaded_by === 'string' && typeof loaded_at === 'string'
    && (approved_by === null || typeof approved_by === 'string')
    && isRecord(content) && typeof content.title === 'string'
    && (content.image_id === null || (typeof content.image_id === 'string' && /^[a-f0-9]{64}$/.test(content.image_id)))
    && Array.isArray(content.parameters) && content.parameters.every(isRecipeParameter);
}
