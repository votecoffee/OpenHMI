export const commandStates = ['prepared', 'staging', 'requested', 'accepted', 'uncertain', 'completed', 'failed', 'interrupted'];

export function isCommandRecord(item) {
  return Number.isSafeInteger(item?.id) && item.id > 0 && Number.isSafeInteger(item.sequence)
    && typeof item.command_id === 'string' && typeof item.operation_id === 'string' && typeof item.created_at === 'string'
    && commandStates.includes(item.state) && (item.result_code === null || Number.isSafeInteger(item.result_code))
    && (item.error === null || typeof item.error === 'string')
    && Array.isArray(item.events) && item.events.every(event => typeof event?.timestamp === 'string'
      && commandStates.includes(event.state) && typeof event.detail === 'string');
}

export function isCommandPage(page) {
  return Array.isArray(page?.items) && page.items.every(isCommandRecord) && typeof page.has_more === 'boolean'
    && (page.has_more ? Number.isSafeInteger(page.next_before_id) && page.next_before_id > 0 : page.next_before_id === null);
}
