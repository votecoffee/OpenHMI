import React, { useState } from 'react';
import { alarmMessage, formatLocalDateTime, useLocalization } from './localization.jsx';
import { hasAlarmMessage, useAlarmRead } from './alarm-read.mjs';

function isShelfPage(page) {
  return Array.isArray(page?.items) && page.items.every(item => hasAlarmMessage(item?.definition)
    && ['alarm_id', 'actor', 'provider', 'reason', 'operation_id', 'expires_at'].every(key => typeof item[key] === 'string')
    && !!item.alarm_id && !!item.operation_id && Number.isFinite(Date.parse(item.expires_at)))
    && typeof page.has_more === 'boolean'
    && (page.has_more ? !!page.next_after_id && page.next_after_id === page.items.at(-1)?.alarm_id : page.next_after_id === null);
}

export function AlarmShelving({ reason, setReason, duration, setDuration, canShelve, busy, generation, restore }) {
  const { ui, language } = useLocalization();
  const [after, setAfter] = useState('');
  const { data: page, error, receivedAt } = useAlarmRead(
    `/api/alarms/shelves?after_id=${encodeURIComponent(after)}`, isShelfPage, generation);
  return <section className="alarm-detail" aria-label={ui('alarmShelving')}><h2>{ui('alarmShelving')}</h2>
    <p>{ui('shelfExplanation')}</p>{error && <p role="alert">{ui('alarmReadError')} {error}
      {page && <> {ui('alarmLastPage', { time: formatLocalDateTime(receivedAt, language.code) })}</>}</p>}
    <div className="alarm-actions"><label>{ui('shelfReason')}<input aria-label={ui('shelfReason')} value={reason} maxLength={1000} disabled={!canShelve || busy} onChange={event => setReason(event.target.value)} /></label>
      <label>{ui('shelfDuration')}<select aria-label={ui('shelfDuration')} value={duration} disabled={!canShelve || busy} onChange={event => setDuration(event.target.value)}>{[15, 30, 60, 120, 480, 1440].map(minutes => <option key={minutes} value={minutes * 60}>{ui('shelfMinutes', { count: minutes })}</option>)}</select></label></div>
    <table><thead><tr><th>{ui('message')}</th><th>{ui('recordedUser')}</th><th>{ui('shelfExpiry')}</th><th>{ui('shelfReason')}</th><th /></tr></thead>
      <tbody>{page?.items.map(item => <tr key={item.alarm_id}><td>{alarmMessage(item.definition, language)}</td><td>{item.actor} ({item.provider})</td><td>{new Date(item.expires_at).toLocaleString(language.code)}</td><td className="alarm-guidance">{item.reason}</td><td><button disabled={!canShelve || busy || !!error || !reason.trim()} onClick={() => restore(item)} aria-label={ui('restoreAlarmNamed', { name: alarmMessage(item.definition, language) })}>{ui('restoreAlarm')}</button></td></tr>)}</tbody></table>
    {page && !page.items.length && <p>{ui('noShelves')}</p>}<button onClick={() => setAfter('')}>{ui('firstShelves')}</button><button disabled={!!error || !page?.has_more} onClick={() => setAfter(page.next_after_id)}>{ui('moreShelves')}</button>
  </section>;
}
