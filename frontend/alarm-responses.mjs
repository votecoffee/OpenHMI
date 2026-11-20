export function hasAlarmMessage(item) {
  return typeof item?.message === 'string' && (item.messages == null || (typeof item.messages === 'object'
    && !Array.isArray(item.messages) && Object.values(item.messages).every(message => typeof message === 'string')));
}

const positiveId = value => Number.isSafeInteger(value) && value > 0;
const optionalText = value => value == null || typeof value === 'string';

function isOccurrence(item) {
  return hasAlarmMessage(item) && positiveId(item.occurrence_id) && [1, 2, 3, 4].includes(item.priority)
    && typeof item.active === 'boolean' && typeof item.raised_at === 'string'
    && [item.acknowledged_at, item.acknowledged_by, item.retired_at].every(optionalText)
    && (item.shelf == null || typeof item.shelf.expires_at === 'string');
}

function isAlarmEvent(item) {
  return positiveId(item?.id) && typeof item.timestamp === 'string' && typeof item.event === 'string'
    && typeof item.alarm_id === 'string' && (item.definition === null || hasAlarmMessage(item.definition))
    && [item.comment, item.actor, item.provider].every(optionalText);
}

function isAlarmNote(item) {
  return positiveId(item?.id) && ['timestamp', 'actor', 'provider', 'comment'].every(key => typeof item[key] === 'string');
}

export function isAlarmDetail(detail, identifier) {
  const { occurrence, trigger, related_screen: screen } = detail ?? {};
  return isOccurrence(occurrence) && occurrence.occurrence_id === identifier && typeof occurrence.tag === 'string'
    && ['cause', 'response', 'related_screen', 'acknowledged_provider', 'acknowledgement_comment']
      .every(key => optionalText(occurrence[key]))
    && ['causes', 'responses'].every(key => occurrence[key] == null || (typeof occurrence[key] === 'object'
      && !Array.isArray(occurrence[key]) && Object.values(occurrence[key]).every(value => typeof value === 'string')))
    && typeof trigger?.quality === 'string' && optionalText(trigger.quality_reason)
    && optionalText(trigger.timestamp) && optionalText(trigger.error)
    && (screen === null || (typeof screen?.id === 'string' && typeof screen.title === 'string'));
}

function isAlarmPage(page, isItem, key, maximum) {
  return Array.isArray(page?.items) && page.items.length <= maximum
    && page.items.every((item, index) => isItem(item)
      && (index === 0 || page.items[index - 1][key] > item[key]))
    && typeof page.has_more === 'boolean'
    && (page.has_more ? page.items.length > 0 && page.next_before_id === page.items.at(-1)[key] : page.next_before_id === null);
}

export const isOccurrencePage = page => isAlarmPage(page, isOccurrence, 'occurrence_id', 200);
export const isEventPage = page => isAlarmPage(page, isAlarmEvent, 'id', 200);
export const isNotePage = page => isAlarmPage(page, isAlarmNote, 'id', 100);

export function isShelfPage(page) {
  return Array.isArray(page?.items) && page.items.length <= 200
    && page.items.every((item, index) => hasAlarmMessage(item?.definition)
      && ['alarm_id', 'actor', 'provider', 'reason', 'operation_id', 'expires_at'].every(key => typeof item[key] === 'string')
      && !!item.alarm_id && !!item.operation_id && Number.isFinite(Date.parse(item.expires_at))
      && (index === 0 || page.items[index - 1].alarm_id < item.alarm_id))
    && typeof page.has_more === 'boolean'
    && (page.has_more ? page.items.length > 0 && page.next_after_id === page.items.at(-1).alarm_id : page.next_after_id === null);
}
