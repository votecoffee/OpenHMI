import React, { useContext, useState } from 'react';
import { Live, PrioritySymbol } from './controls.jsx';
import { useLocalization, LanguageSelector, alarmMessage } from './localization.jsx';
import { api, json } from './api.mjs';
import { SecurityContext, allowed } from './security.jsx';

export function AlarmConsole() {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const canAcknowledge = allowed(session, 'alarms.acknowledge');
  const { language, ui } = useLocalization();
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const alarms = live.alarms || { outstanding: [], occurrences: [], history: [] };
  async function acknowledge(identifier) {
    setBusy(true);
    try {
      await api(identifier == null ? '/api/alarms/acknowledge-all' : `/api/alarms/${identifier}/acknowledge`, json('POST', {}));
      setFeedback(ui('acknowledged'));
    } catch (error) { setFeedback(error.message); }
    finally { setBusy(false); }
  }
  function timestamp(value) {
    if (!value) return '—';
    try { return new Date(value).toLocaleString(language.code); } catch { return value; }
  }
  return <section className="alarm-console" aria-label="Alarm console">
    <div className="alarm-console-heading"><h1>{ui('alarmStatus')}</h1><LanguageSelector /></div>
    {!live.alarmConnected || alarms.error ? <p role="alert">{ui('alarmUnavailable')}</p> : <p>{ui('activeAlarms', { active: alarms.active_count, unack: alarms.unacknowledged_count })}</p>}
    <button disabled={busy || !canAcknowledge || !alarms.unacknowledged_count} onClick={() => acknowledge(null)}>{ui('acknowledgeAll')}</button>
    <span role="status" aria-label="Alarm operation">{feedback}</span>
    <table><thead><tr><th>{ui('priority')}</th><th>{ui('message')}</th><th>{ui('status')}</th><th>{ui('raised')}</th><th /></tr></thead>
      <tbody>{alarms.outstanding.map(alarm => <tr key={alarm.occurrence_id}><td><PrioritySymbol priority={alarm.priority} />P{alarm.priority}</td>
        <td>{alarmMessage(alarm, language)}</td><td>{alarm.retired_at ? ui('retired') : alarm.active ? ui('active') : ui('returned')} / {alarm.acknowledged_at ? ui('acknowledged') : ui('unacknowledged')}
          {alarm.quality === 'bad' && <> / {ui('badData')}</>}</td><td>{timestamp(alarm.raised_at)}</td>
        <td><button disabled={busy || !canAcknowledge || !!alarm.acknowledged_at} onClick={() => acknowledge(alarm.occurrence_id)} aria-label={`${ui('acknowledge')} ${alarmMessage(alarm, language)}`}>{ui('acknowledge')}</button></td></tr>)}</tbody></table>
    {!alarms.outstanding.length && <p>{ui('noOutstanding')}</p>}
    <h2>{ui('alarmHistory')}</h2><table><thead><tr><th>{ui('time')}</th><th>{ui('event')}</th><th>{ui('message')}</th></tr></thead><tbody>
      {alarms.history.map(event => {
        const occurrence = alarms.occurrences.find(item => item.occurrence_id === event.occurrence_id);
        return <tr key={event.id}><td>{timestamp(event.timestamp)}</td><td>{ui(event.event)}</td><td>{occurrence ? alarmMessage(occurrence, language) : event.alarm_id}</td></tr>;
      })}
    </tbody></table>{!alarms.history.length && <p>{ui('noHistory')}</p>}
  </section>;
}
