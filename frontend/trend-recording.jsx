import React, { useContext, useEffect, useState } from 'react';
import { api, json } from './api.mjs';
import { SecurityContext, allowed } from './security.jsx';
import { formatLocalDateTime, useLocalization } from './localization.jsx';

const defaults = { sample_ms: 250, max_samples: 4000, start_tag: '', stop_tag: '' };
const stopReasons = new Map([
  ['manual stop', 'trendManualStop'],
  ['stop trigger', 'trendStopTrigger'],
  ['runtime stopped', 'trendRuntimeStopped'],
  ['configuration changed', 'trendConfigurationChanged'],
  ['interrupted', 'trendInterrupted'],
]);

export function TrendRecordingFields({ value, onChange, catalog }) {
  const tags = catalog.tags.filter(tag => tag.type === 'boolean');
  const set = (key, next) => onChange({ ...value, [key]: next });
  return <fieldset className="trend-fields"><legend>Saved trend recording</legend>
    <label><span>Enable recording</span><input type="checkbox" checked={!!value}
      onChange={event => onChange(event.target.checked ? { ...defaults } : null)} /></label>
    {value && <>
      <label>Record interval (ms)<input type="number" min="100" max="60000" value={value.sample_ms ?? ''}
        onChange={event => set('sample_ms', event.target.valueAsNumber || null)} /></label>
      <label>Retained samples per capture<input type="number" min="10" max="20000" value={value.max_samples ?? ''}
        onChange={event => set('max_samples', event.target.valueAsNumber || null)} /></label>
      {['start_tag', 'stop_tag'].map(key => <label key={key}>{key === 'start_tag' ? 'Start trigger tag' : 'Stop trigger tag'}
        <select value={value[key]} onChange={event => set(key, event.target.value)}>
          <option value="">Manual only</option>
          {tags.map(tag => <option key={tag.name} value={tag.name}>{tag.name}</option>)}
        </select>
      </label>)}
      <small>Trigger tags use sampled rising edges. Each run keeps its newest samples.</small>
    </>}
  </fieldset>;
}

function isCaptureStatus(status) {
  const epoch = value => Number.isFinite(value) && Math.abs(value) <= 8.64e12;
  const optionalEpoch = value => value === null || epoch(value);
  const count = value => Number.isSafeInteger(value) && value >= 0;
  return typeof status?.enabled === 'boolean' && (status.error == null || typeof status.error === 'string')
    && Array.isArray(status.captures) && status.captures.every(item => count(item?.id) && item.id > 0
      && epoch(item.started) && optionalEpoch(item.stopped) && optionalEpoch(item.first) && optionalEpoch(item.last)
      && (item.reason == null || typeof item.reason === 'string')
      && [item.retained, item.max_samples, item.rolled_off].every(count)
      && Array.isArray(item.series) && item.series.every(pen => typeof pen?.tag === 'string'
        && ['number', 'boolean'].includes(pen.type)
        && (pen.decimals == null || (count(pen.decimals) && pen.decimals <= 8))
        && (pen.minimum == null || Number.isFinite(pen.minimum)) && (pen.maximum == null || Number.isFinite(pen.maximum))));
}

export function useTrendCaptures(id, editing, recording) {
  const [response, setResponse] = useState(null);
  const [error, setError] = useState('');
  const [selection, setSelection] = useState('auto');
  const [busy, setBusy] = useState(false);
  const url = '/api/trends/' + encodeURIComponent(id);
  const current = response?.url === url ? response : null;
  const status = current?.status;
  const available = current?.available === true;
  useEffect(() => {
    if (editing || busy) return;
    let stopped = false, timer;
    async function poll() {
      let retry = recording;
      try {
        const next = await api(url);
        if (!isCaptureStatus(next)) throw new Error('Invalid recording status response');
        if (!stopped) setResponse({ url, status: next, available: true });
      } catch (problem) {
        const discard = [401, 403, 404].includes(problem.status);
        retry = true;
        if (!stopped) setResponse(previous => ({ url, available: false,
          status: !discard && previous?.url === url ? previous.status : null }));
      }
      if (!stopped && retry) timer = setTimeout(poll, 1000);
    }
    poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [url, editing, recording, busy]);

  const captures = status?.captures ?? [];
  const running = captures.find(item => item.stopped === null);
  const capture = selection === 'auto' ? running ?? captures[0] : captures.find(item => String(item.id) === selection);

  async function command(action, captureId) {
    if (!available || busy) return;
    setBusy(true);
    try {
      await api(url, json('POST', { action, capture_id: captureId }));
      if (action === 'start' || action === 'delete') setSelection('auto');
      setError('');
    } catch (problem) {
      setError(problem.message);
    } finally {
      setResponse(previous => previous?.url === url ? { ...previous, available: null } : previous);
      setBusy(false);
    }
  }
  return { enabled: status?.enabled ?? recording, captures, running, capture, selection, setSelection, busy, command,
    available, unavailable: current?.available === false, retainedStatus: !!status, error: error || status?.error };
}

export function CaptureTools({ state, recording, setEndTime, endTime }) {
  const { session } = useContext(SecurityContext) ?? {};
  const { language, ui } = useLocalization();
  const { enabled, captures, running, capture, selection, setSelection, command, busy, error,
    available, unavailable, retainedStatus } = state;
  const blocked = busy || !available;
  const [confirm, setConfirm] = useState(null);
  if (!recording && !captures.length) return null;
  const canOperate = allowed(session, 'runtime.operate');
  const canDelete = allowed(session, 'project.edit');
  function select(source) {
    setSelection(source);
    setEndTime(null);
    setConfirm(null);
  }
  const last = capture?.last;
  const first = capture?.first;
  const captureDate = epoch => formatLocalDateTime(new Date(epoch * 1000), language.code);
  const reasonKey = stopReasons.get(capture?.reason);
  return <div className="trend-captures">
    <div className="trend-tools">
      <label>{ui('trendData')}<select value={selection} onChange={event => select(event.target.value)}>
        <option value="auto">{ui('trendAutoSource')}</option>
        <option value="history">{ui('trendHistorySource')}</option>
        {captures.map(item => <option key={item.id} value={item.id}>{ui('trendCaptureOption', { id: item.id, time: captureDate(item.started) })}</option>)}
      </select></label>
      {enabled && <button type="button" disabled={blocked || !!running || !canOperate}
        onClick={() => { setEndTime(null); command('start', 0); }}>{ui('trendRun')}</button>}
      {enabled && <button type="button" disabled={blocked || !running || !canOperate}
        onClick={() => command('stop', running.id)}>{ui('trendStop')}</button>}
      <span role="status">{unavailable ? <>{ui('trendRecordingUnavailable')}
        {retainedStatus && <> · {ui('trendLastRecordingStatus')}</>}</>
        : !available ? ui('trendRecordingWaiting') : running ? ui('trendRecording', { id: running.id })
          : enabled && recording?.start_tag ? ui('trendArmed') : enabled ? ui('trendStopped') : ''}</span>
    </div>
    {capture && <>
      <span>{ui('trendRetention', { id: capture.id, retained: capture.retained, max: capture.max_samples })}
        {capture.rolled_off > 0 && ` · ${ui('trendRolledOff', { count: capture.rolled_off })}`}
        {capture.reason && ` · ${reasonKey ? ui(reasonKey) : capture.reason}`}</span>
      {first != null && last > first && <label className="trend-seek">{ui('trendCapturePosition')}
        <input type="range" min={first} max={last} step="any" value={Math.max(first, Math.min(last, endTime ?? last))}
          aria-valuetext={captureDate(endTime ?? last)}
          onChange={event => setEndTime(event.target.valueAsNumber)} />
      </label>}
      <div className="trend-tools"><a href={`/api/trend-captures/${capture.id}/csv`}>{ui('trendExportCapture')}</a>
        {canDelete && capture.stopped !== null && (confirm === capture.id ? <>
          <button type="button" disabled={blocked} onClick={() => { command('delete', capture.id); setConfirm(null); setEndTime(null); }}>{ui('trendConfirmDelete')}</button>
          <button type="button" onClick={() => setConfirm(null)}>{ui('cancelEntry')}</button>
        </> : <button type="button" disabled={blocked} onClick={() => setConfirm(capture.id)}>{ui('trendDeleteCapture')}</button>)}
      </div>
    </>}
    {error && <span role="alert" className="hmi-quality">{error}</span>}
  </div>;
}
