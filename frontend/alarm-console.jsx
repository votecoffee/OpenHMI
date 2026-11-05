import React, { useContext, useEffect, useRef, useState } from 'react';
import { PrioritySymbol } from './controls.jsx';
import { Live } from './live-quality.jsx';
import { useLocalization, LanguageSelector, alarmMessage } from './localization.jsx';
import { api, json } from './api.mjs';
import { SecurityContext, allowed } from './security.jsx';
import './alarm-workflows.css';
import { AlarmShelving } from './alarm-shelving.jsx';

const blankFilters = { priority: '0', search: '', state: 'outstanding', start: '', end: '', shelving: new URLSearchParams(location.search).get('shelving') === 'shelved' ? 'shelved' : 'unshelved' };
function linkedOccurrence() {
  const value = new URLSearchParams(location.search).get('occurrence');
  const id = Number(value);
  return /^[1-9]\d*$/.test(value ?? '') && Number.isSafeInteger(id) ? id : null;
}
function parameters(filters, before, history = false, event = '') {
  const query = new URLSearchParams({ priority: filters.priority, search: filters.search, state: history ? 'all' : filters.state });
  if (!history) query.set('shelving', filters.shelving);
  for (const field of ['start', 'end']) if (filters[field]) query.set(field, new Date(filters[field]).toISOString());
  if (before) query.set('before_id', before);
  if (event) query.set('event', event);
  return query;
}

export function AlarmConsole() {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const canAcknowledge = allowed(session, 'alarms.acknowledge');
  const canComment = allowed(session, 'alarms.comment');
  const canShelve = allowed(session, 'alarms.shelve');
  const [shelfReason, setShelfReason] = useState(''), [shelfDuration, setShelfDuration] = useState('900');
  const { language, ui } = useLocalization();
  const [feedback, setFeedback] = useState(''), [busy, setBusy] = useState(false);
  const [filters, setFilters] = useState(blankFilters), [applied, setApplied] = useState(blankFilters);
  const [before, setBefore] = useState(null), [eventBefore, setEventBefore] = useState(null), [eventFilter, setEventFilter] = useState('');
  const [rows, setRows] = useState(null), [history, setHistory] = useState(null), [error, setError] = useState('');
  const [selected, setSelected] = useState([]), [comment, setComment] = useState('');
  const [identifier, setIdentifier] = useState(linkedOccurrence), [detail, setDetail] = useState(null), [detailError, setDetailError] = useState('');
  const detailHeading = useRef(null);
  const detailReady = Boolean(detail || detailError);
  const [note, setNote] = useState(''), [notesBefore, setNotesBefore] = useState(null), [notes, setNotes] = useState(null);
  const [generation, setGeneration] = useState(0);
  const alarms = live.alarms || {};
  useEffect(() => {
    let stopped = false, timer;
    async function refresh() {
      try {
        const [occurrences, events] = await Promise.all([api(`/api/alarms/occurrences?${parameters(applied, before)}`), api(`/api/alarms/events?${parameters(applied, eventBefore, true, eventFilter)}`)]);
        if (!stopped) { setRows(occurrences); setHistory(events); setError(''); setSelected(previous => previous.filter(id => occurrences.items.some(item => item.occurrence_id === id && !item.acknowledged_at))); }
      } catch (problem) { if (!stopped) setError(problem.message); }
      if (!stopped) timer = setTimeout(refresh, 1000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [applied, before, eventBefore, eventFilter, generation]);
  useEffect(() => {
    if (!identifier) return;
    let stopped = false, timer;
    async function refresh() {
      try { const [next, page] = await Promise.all([api(`/api/alarms/occurrences/${identifier}`), api(`/api/alarms/occurrences/${identifier}/notes${notesBefore ? `?before_id=${notesBefore}` : ''}`)]); if (!stopped) { setDetail(next); setNotes(page); setDetailError(''); } }
      catch (problem) { if (!stopped) setDetailError(problem.message); }
      if (!stopped) timer = setTimeout(refresh, 1000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [identifier, notesBefore, generation]);
  useEffect(() => {
    if (detailReady) detailHeading.current?.focus();
  }, [identifier, detailReady]);
  async function acknowledge(id, batch = false) {
    setBusy(true);
    try {
      const path = batch ? '/api/alarms/acknowledge-selected' : id == null ? '/api/alarms/acknowledge-all' : `/api/alarms/${id}/acknowledge`;
      const result = await api(path, json('POST', { comment, ...(batch ? { occurrence_ids: selected } : {}) }));
      setFeedback(result.audit_status === 'pending' ? ui('alarmAckPending', { id: result.operation_id }) : ui('acknowledgedCount', { count: result.acknowledged.length }));
      setSelected([]); setGeneration(value => value + 1);
    } catch (problem) { setFeedback(problem.message); }
    finally { setBusy(false); }
  }
  async function saveNote(event) {
    event.preventDefault(); setBusy(true);
    try { const result = await api(`/api/alarms/occurrences/${identifier}/notes`, json('POST', { comment: note })); setNote(''); setNotesBefore(null); setGeneration(value => value + 1); setFeedback(result.audit_status === 'pending' ? ui('alarmNotePending', { id: result.operation_id }) : ui('noteSaved')); }
    catch (problem) { setFeedback(problem.message); }
    finally { setBusy(false); }
  }
  function timestamp(value) {
    if (!value) return '—';
    try { return new Date(value).toLocaleString(language.code); } catch { return value; }
  }
  async function changeShelf(item = null) {
    setBusy(true);
    try {
      const result = item ? await api(`/api/alarms/shelves/${encodeURIComponent(item.alarm_id)}/restore`, json('POST', { expected_operation_id: item.operation_id, reason: shelfReason }))
        : await api(`/api/alarms/occurrences/${identifier}/shelve`, json('POST', { duration_seconds: Number(shelfDuration), reason: shelfReason }));
      setFeedback(result.audit_status === 'pending' ? ui('shelfPending', { id: result.operation_id }) : ui(item ? 'shelfRestored' : 'shelfSaved'));
      setSelected([]); setGeneration(value => value + 1);
    } catch (problem) { setFeedback(problem.message); }
    finally { setBusy(false); }
  }
  function guidance(alarm, field) { return alarm[field + 's']?.[language.code] || alarm[field] || ui('noGuidance'); }
  function inspect(id) { setIdentifier(id); setDetail(null); setNotes(null); setNotesBefore(null); setDetailError(''); setNote(''); }
  return <section className="alarm-console" aria-label="Alarm console">
    <div className="alarm-console-heading"><h1>{ui('alarmStatus')}</h1><LanguageSelector /></div>
    {!live.alarmConnected || alarms.error ? <p role="alert">{ui('alarmUnavailable')}</p> : <p>{ui('activeAlarms', { active: alarms.active_count, unack: alarms.unacknowledged_count })}</p>}
    <p>{ui('alarmCountsHint')}</p>
    {!!alarms.shelved_count && <p>{ui('shelvedSummary', { count: alarms.shelved_count })}</p>}
    <form className="alarm-filters" onSubmit={event => { event.preventDefault(); setApplied({ ...filters }); setBefore(null); setEventBefore(null); setSelected([]); }}>
      <label>{ui('alarmSearch')}<input aria-label={ui('alarmSearch')} value={filters.search} maxLength={200} onChange={event => setFilters({ ...filters, search: event.target.value })} /></label>
      <label>{ui('priority')}<select aria-label={ui('priority')} value={filters.priority} onChange={event => setFilters({ ...filters, priority: event.target.value })}><option value="0">{ui('allPriorities')}</option>{[1, 2, 3, 4].map(value => <option key={value} value={value}>P{value}</option>)}</select></label>
      <label>{ui('alarmStateFilter')}<select aria-label={ui('alarmStateFilter')} value={filters.state} onChange={event => setFilters({ ...filters, state: event.target.value })}>{['outstanding', 'active', 'unacknowledged', 'returned', 'acknowledged', 'retired', 'all'].map(value => <option key={value} value={value}>{value === 'all' ? ui('allStates') : ui(value)}</option>)}</select></label>
      <label>{ui('shelfFilter')}<select aria-label={ui('shelfFilter')} value={filters.shelving} onChange={event => setFilters({ ...filters, shelving: event.target.value })}>{['unshelved', 'shelved', 'all'].map(value => <option key={value} value={value}>{ui(value === 'all' ? 'allShelving' : value)}</option>)}</select></label>
      {['start', 'end'].map(field => <label key={field}>{ui(field === 'start' ? 'alarmStart' : 'alarmEnd')}<input aria-label={ui(field === 'start' ? 'alarmStart' : 'alarmEnd')} type="datetime-local" value={filters[field]} onChange={event => setFilters({ ...filters, [field]: event.target.value })} /></label>)}
      <button>{ui('filterAlarms')}</button>
    </form>
    {error && <p role="alert">{ui('alarmReadError')} {error}</p>}
    <div className="alarm-actions"><label>{ui('acknowledgementComment')}<input aria-label={ui('acknowledgementComment')} value={comment} maxLength={1000} onChange={event => setComment(event.target.value)} /></label>
      <button disabled={busy || !!error || !canAcknowledge || !rows?.items.some(item => !item.acknowledged_at)} onClick={() => setSelected(rows.items.filter(item => !item.acknowledged_at).map(item => item.occurrence_id))}>{ui('selectAlarmPage')}</button>
      <span>{ui('selectedCount', { count: selected.length })}</span><button disabled={busy || !!error || !canAcknowledge || !selected.length} onClick={() => acknowledge(null, true)}>{ui('acknowledgeSelected')}</button>
      <button disabled={busy || !!error || !canAcknowledge || !alarms.unacknowledged_count} onClick={() => acknowledge(null)}>{ui('acknowledgeAll')}</button></div>
    <p role="status" aria-label="Alarm operation">{feedback}</p>
    <table className="alarm-occurrences"><thead><tr><th /><th>{ui('priority')}</th><th>{ui('message')}</th><th>{ui('status')}</th><th>{ui('raised')}</th><th /></tr></thead>
      <tbody>{rows?.items.map(alarm => <tr key={alarm.occurrence_id}><td><input type="checkbox" aria-label={ui('selectAlarm', { id: alarm.occurrence_id })} disabled={busy || !!error || !canAcknowledge || !!alarm.acknowledged_at} checked={selected.includes(alarm.occurrence_id)} onChange={event => setSelected(previous => event.target.checked ? [...previous, alarm.occurrence_id] : previous.filter(id => id !== alarm.occurrence_id))} /></td>
        <td><PrioritySymbol priority={alarm.priority} />P{alarm.priority}</td><td>{alarmMessage(alarm, language)}</td>
        <td>{alarm.retired_at ? ui('retired') : alarm.active ? ui('active') : ui('returned')} / {alarm.acknowledged_at ? ui('acknowledged') : ui('unacknowledged')}{alarm.quality === 'bad' && <> / {ui('badData')}</>}
          {alarm.acknowledged_at && <small>{ui('acknowledgedBy')}: {alarm.acknowledged_by || ui('legacyIdentity')}</small>}{alarm.shelf && <small>{ui('shelved')} · {timestamp(alarm.shelf.expires_at)}</small>}</td><td>{timestamp(alarm.raised_at)}</td>
        <td><button disabled={busy || !!error || !canAcknowledge || !!alarm.acknowledged_at} onClick={() => acknowledge(alarm.occurrence_id)} aria-label={`${ui('acknowledge')} ${alarmMessage(alarm, language)}`}>{ui('acknowledge')}</button><button aria-label={ui('inspectAlarm', { id: alarm.occurrence_id })} onClick={() => inspect(alarm.occurrence_id)}>{ui('alarmDetails')}</button></td></tr>)}</tbody></table>
    {rows && !rows.items.length && <p>{applied.state === 'outstanding' && !applied.search && applied.priority === '0' && !applied.start && !applied.end && applied.shelving === 'unshelved' ? ui(alarms.shelved_occurrence_count ? 'noUnshelvedAlarms' : 'noOutstanding') : ui('alarmFilteredEmpty')}</p>}
    <button onClick={() => { setBefore(null); setSelected([]); }}>{ui('newestAlarms')}</button><button disabled={!rows?.has_more} onClick={() => { setBefore(rows.next_before_id); setSelected([]); }}>{ui('olderAlarms')}</button>
    <AlarmShelving reason={shelfReason} setReason={setShelfReason} duration={shelfDuration} setDuration={setShelfDuration} canShelve={canShelve} busy={busy} generation={generation} restore={changeShelf} />
    {identifier && <section className="alarm-detail" aria-label={ui('alarmDetails')}><h2 ref={detailHeading} tabIndex={-1}>{ui('alarmDetails')} #{identifier}</h2>{detailError && <p role="alert">{ui('alarmReadError')} {detailError}</p>}
      {detail && <><h3>{alarmMessage(detail.occurrence, language)}</h3><p>{ui('triggerQuality')}: {detail.trigger.quality} · {timestamp(detail.trigger.timestamp)} {detail.trigger.error}</p>
        <p>{detail.occurrence.shelf ? `${ui('shelved')} · ${timestamp(detail.occurrence.shelf.expires_at)}` : ui('unshelved')}</p><button disabled={!canShelve || busy || !!detailError || !!detail.occurrence.shelf || !!detail.occurrence.retired_at || (!detail.occurrence.active && !!detail.occurrence.acknowledged_at) || !shelfReason.trim()} onClick={() => changeShelf()}>{ui('shelveAlarm')}</button>
        <h3>{ui('possibleCause')}</h3><p className="alarm-guidance">{guidance(detail.occurrence, 'cause')}</p><h3>{ui('operatorResponse')}</h3><p className="alarm-guidance">{guidance(detail.occurrence, 'response')}</p>
        {detail.related_screen && <a href={`/runtime?screen=${encodeURIComponent(detail.related_screen.id)}`}>{ui('openRelatedScreen')}: {detail.related_screen.title}</a>}{!detail.related_screen && detail.occurrence.related_screen && <p>{ui('relatedScreenUnavailable')}</p>}
        <p>{ui('acknowledgedBy')}: {detail.occurrence.acknowledged_by || (detail.occurrence.acknowledged_at ? ui('legacyIdentity') : ui('unacknowledged'))} {detail.occurrence.acknowledged_provider} · {timestamp(detail.occurrence.acknowledged_at)}</p><p>{detail.occurrence.acknowledgement_comment}</p>
        <h3>{ui('operatorNotes')}</h3><form onSubmit={saveNote}><label>{ui('operatorNote')}<textarea aria-label={ui('operatorNote')} maxLength={1000} value={note} onChange={event => setNote(event.target.value)} disabled={!canComment || busy || !!detailError} /></label><button disabled={!canComment || busy || !!detailError || !note.trim()}>{ui('saveOperatorNote')}</button></form>
        <table><tbody>{notes?.items.map(item => <tr key={item.id}><td>{timestamp(item.timestamp)}<br />{item.actor} ({item.provider})</td><td className="alarm-guidance">{item.comment}</td></tr>)}</tbody></table>
        <button onClick={() => setNotesBefore(null)}>{ui('newestNotes')}</button><button disabled={!notes?.has_more} onClick={() => setNotesBefore(notes.next_before_id)}>{ui('olderNotes')}</button>
      </>}
    </section>}
    <h2>{ui('alarmHistory')}</h2><p>{ui('alarmHistoryHint')}</p><div className="alarm-actions"><label>{ui('alarmEventFilter')}<select aria-label={ui('alarmEventFilter')} value={eventFilter} onChange={event => { setEventFilter(event.target.value); setEventBefore(null); }}><option value="">{ui('allEvents')}</option>{['active', 'returned', 'acknowledged', 'quality_bad', 'quality_recovered', 'configuration_changed', 'operator_note', 'shelved', 'shelf_restored', 'shelf_expired', 'shelf_invalidated'].map(value => <option key={value} value={value}>{ui(value)}</option>)}</select></label><a href={`/api/alarms/events.csv?${parameters(applied, null, true, eventFilter)}`}>{ui('exportAlarmCsv')}</a></div>
    <table className="alarm-events"><thead><tr><th>{ui('time')}</th><th>{ui('event')}</th><th>{ui('message')}</th><th>{ui('recordedUser')}</th></tr></thead><tbody>{history?.items.map(item => <tr key={item.id}>
      <td>{timestamp(item.timestamp)}</td><td>{ui(item.event)}</td><td>{item.definition ? alarmMessage(item.definition, language) : item.alarm_id}{item.comment && <p className="alarm-guidance">{item.comment}</p>}</td><td>{item.actor || ui('legacyIdentity')} {item.provider}</td>
    </tr>)}</tbody></table>{history && !history.items.length && <p>{ui('noHistory')}</p>}
    <button onClick={() => setEventBefore(null)}>{ui('newestEvents')}</button><button disabled={!history?.has_more} onClick={() => setEventBefore(history.next_before_id)}>{ui('olderEvents')}</button>
  </section>;
}
