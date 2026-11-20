import { isCommandRecord } from './command-status.mjs';

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const positiveId = value => Number.isSafeInteger(value) && value > 0;
const optionalText = value => value == null || typeof value === 'string';

export function isRecipeTransferRecord(item) {
  const snapshot = item?.snapshot;
  return record(item) && positiveId(item.id) && typeof item.profile_id === 'string'
    && typeof item.profile?.name === 'string' && record(snapshot)
    && typeof snapshot.code === 'string' && positiveId(snapshot.number)
    && typeof snapshot.production_approved === 'boolean' && typeof snapshot.content?.title === 'string'
    && (snapshot.content.image_id == null || snapshot.content.image_id === ''
      || (typeof snapshot.content.image_id === 'string' && /^[a-f0-9]{64}$/.test(snapshot.content.image_id)))
    && [snapshot.approved_by, snapshot.transferred_by, snapshot.transfer_reason, snapshot.content_hash, item.transfer_hash].every(optionalText)
    && isCommandRecord(item.transaction) && item.transaction.id === item.id && optionalText(item.transaction.updated_at);
}

export function isRecipeTransferPage(page) {
  const profiles = new Set();
  return record(page) && positiveId(page.active_revision) && Array.isArray(page.profiles)
    && page.profiles.every(profile => {
      if (typeof profile?.id !== 'string' || !profile.id || typeof profile.name !== 'string' || profiles.has(profile.id)) return false;
      profiles.add(profile.id); return true;
    }) && Array.isArray(page.unresolved_profiles) && page.unresolved_profiles.every(id => typeof id === 'string')
    && typeof page.has_history === 'boolean' && typeof page.verified_profile === 'string'
    && (page.verified === null || (isRecipeTransferRecord(page.verified) && page.verified.transaction.state === 'completed'))
    && Array.isArray(page.items) && page.items.length <= 100
    && page.items.every((item, index) => isRecipeTransferRecord(item) && (index === 0 || page.items[index - 1].id > item.id))
    && (page.has_history || page.items.length === 0) && typeof page.has_more === 'boolean'
    && (page.has_more ? page.items.length > 0 && page.next_before_id === page.items.at(-1).id : page.next_before_id === null);
}

const operationId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);

export function requireRecipeTransferReceipt(result, { profileId, revisionId, revisionVersion } = {}) {
  const transaction = result?.transaction, transfer = result?.transfer;
  if (result?.ok !== true || !positiveId(revisionId) || !positiveId(revisionVersion)
    || typeof profileId !== 'string' || !profileId || !isCommandRecord(transaction) || !isRecipeTransferRecord(transfer)
    || !operationId(transaction.operation_id) || transaction.state !== 'requested' || transfer.transaction.state !== transaction.state
    || transaction.id !== transfer.id || transaction.sequence !== transfer.transaction.sequence
    || !record(transfer.envelope) || transfer.envelope.sequence !== transaction.sequence
    || transaction.command_id !== transfer.transaction.command_id || transaction.operation_id !== transfer.transaction.operation_id
    || transfer.profile_id !== profileId || transfer.snapshot.id !== revisionId || transfer.snapshot.version !== revisionVersion
    || (result.operation_id != null && result.operation_id !== transaction.operation_id)
    || (result.audit_status != null && !['succeeded', 'pending'].includes(result.audit_status))) {
    const error = new Error('Invalid recipe transfer receipt.');
    error.receipt_invalid = true;
    if (operationId(result?.operation_id)) error.operation_id = result.operation_id;
    if (typeof result?.audit_status === 'string') error.audit_status = result.audit_status;
    throw error;
  }
  return result;
}

export function recipeTransferFailureMessage(problem) {
  let message = typeof problem?.message === 'string' && problem.message ? problem.message : 'Recipe transfer request failed.';
  const uncertain = problem?.receipt_invalid || !Number.isInteger(problem?.status) || problem.status >= 500
    || ['pending', 'uncertain'].includes(problem?.audit_status);
  if (uncertain && !/verify.*before retrying/i.test(message)) message += ' Verify transfer history and PLC state before retrying.';
  if (operationId(problem?.operation_id) && !message.includes(problem.operation_id)) message += ` Operation ${problem.operation_id}.`;
  return message;
}
