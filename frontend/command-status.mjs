export const commandStates = ['prepared', 'staging', 'requested', 'accepted', 'uncertain', 'completed', 'failed', 'interrupted'];

export function isCommandRecord(item) {
  return Number.isSafeInteger(item?.id) && item.id > 0 && Number.isSafeInteger(item.sequence)
    && item.sequence > 0 && item.sequence <= 2147483647
    && typeof item.command_id === 'string' && typeof item.operation_id === 'string' && typeof item.created_at === 'string'
    && commandStates.includes(item.state) && (item.result_code === null || Number.isSafeInteger(item.result_code))
    && (item.error === null || typeof item.error === 'string')
    && Array.isArray(item.events) && item.events.every(event => typeof event?.timestamp === 'string'
      && commandStates.includes(event.state) && typeof event.detail === 'string');
}

export function isCommandPage(page) {
  return Array.isArray(page?.items) && page.items.length <= 200
    && page.items.every((item, index) => isCommandRecord(item)
      && (index === 0 || page.items[index - 1].id > item.id))
    && typeof page.has_more === 'boolean'
    && (page.has_more ? page.items.length > 0 && page.next_before_id === page.items.at(-1).id : page.next_before_id === null);
}
