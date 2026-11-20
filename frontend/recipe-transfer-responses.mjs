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
