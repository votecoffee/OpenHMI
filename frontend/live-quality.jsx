import React, { createContext, useContext, useState } from 'react';
import { formatLocalDateTime, useLocalization, useUi } from './localization.jsx';
import { Popup } from './touch-entry.jsx';

export const Live = createContext({ values: {}, connected: false });

const problems = {
  held: 'tagHeld', disabled: 'tagDisabled', disconnected: 'tagPlcOffline',
  recovering: 'tagRecovering', pending: 'tagWaiting', stale: 'tagStale', unavailable: 'tagUnavailable',
};

export function sampleQualityProblem(sample) {
  if (sample?.quality === 'good') return null;
  const reason = sample?.quality_reason || sample?.quality;
  return typeof reason === 'string' && Object.hasOwn(problems, reason) ? problems[reason] : 'badData';
}

export function tagQuality(live, tag) {
  if (!live.connected) return 'commLoss';
  const sample = live.samples && Object.hasOwn(live.samples, tag) ? live.samples[tag] : undefined;
  if (sample !== undefined) return sampleQualityProblem(sample);
  return Object.hasOwn(live.values, tag) ? null : 'badData';
}

export function tagValue(live, tag, type) {
  const value = live.values[tag];
  const invalid = value == null || (type && typeof value !== type) || (type === 'number' && !Number.isFinite(value));
  const problem = tagQuality(live, tag) || (invalid ? 'badData' : null);
  return { value, valid: !problem, problem };
}

export function useValue(tag, type) {
  return tagValue(useContext(Live), tag, type);
}

function plcBinding(project, tag) {
  const definition = project?.tags?.find(item => item.name === tag
    || (tag.startsWith(item.name + '.') && Object.hasOwn(item.members || {}, tag.slice(item.name.length + 1))));
  if (!definition?.connection) return null;
  const connection = project.connections?.find(item => item.id === definition.connection);
  return {
    id: definition.connection,
    address: definition.address + tag.slice(definition.name.length),
    connection: connection?.name || definition.connection,
    route: connection?.path,
  };
}

export function Quality({ problem, tag, text, sample: suppliedSample, showAge }) {
  const live = useContext(Live);
  const { language } = useLocalization() || { language: { code: 'en' } };
  const ui = useUi();
  const sample = suppliedSample ?? live.samples?.[tag];
  const [opener, setOpener] = useState(null);
  const age = sample?.age_seconds;
  const sourceTime = typeof sample?.timestamp === 'string' ? new Date(sample.timestamp) : null;
  const reason = typeof sample?.error === 'string' ? sample.error : '';
  const ageText = Number.isFinite(age) ? ui('tagSampleAge', { age: age.toFixed(1) }) : '';
  const timeText = sourceTime && Number.isFinite(sourceTime.getTime()) ? formatLocalDateTime(sourceTime, language.code) : '';
  const label = text ?? ui(problem);
  const title = [label, reason, ageText, timeText].filter(Boolean).join(' · ');
  const good = problem === 'tagGood';
  const badgeClass = good ? 'hmi-quality hmi-quality-good' : 'hmi-quality';
  const badge = <><span aria-hidden="true">{good ? '✓' : '×'}</span> {label}
    {(showAge ?? (problem === 'tagStale')) && ageText && <small>{ageText}</small>}
  </>;
  if (!tag) return <span className={badgeClass} title={title}>{badge}</span>;
  const source = opener ? plcBinding(live.project, tag) : null;
  const diagnosticQuery = source && live.diagnosticsPermitted
    ? new URLSearchParams({ search: tag.slice(0, 100), connection: source.id }) : null;
  return <>
    <button type="button" className={badgeClass + ' hmi-quality-inspect'} title={title}
      aria-label={ui('tagInspectQuality', { tag, label })} aria-haspopup="dialog"
      onClick={event => setOpener(event.currentTarget)}>{badge}</button>
    {opener && <Popup title={ui('tagQualityDetails')} opener={opener} close={() => setOpener(null)}>
      <dl className="quality-details">
        <dt>{ui('tagQualityBinding')}</dt><dd>{tag}</dd>
        {source && <>
          <dt>{ui('tagPlcConnection')}</dt><dd>{source.connection}</dd>
          <dt>{ui('tagPlcAddress')}</dt><dd>{source.address}</dd>
          {source.route && <><dt>{ui('tagPlcRoute')}</dt><dd>{source.route}</dd></>}
        </>}
        <dt>{ui('status')}</dt><dd>{label}</dd>
        {reason && <><dt>{ui('tagQualityReason')}</dt><dd>{reason}</dd></>}
        {timeText && <><dt>{ui('tagSourceTime')}</dt><dd>{timeText}</dd></>}
        {ageText && <><dt>{ui('tagAge')}</dt><dd>{ageText}</dd></>}
      </dl>
      {diagnosticQuery && <a href={`/diagnostics?${diagnosticQuery}`} target="_blank" rel="noopener">{ui('tagOpenDiagnostics')}</a>}
    </Popup>}
  </>;
}

export function alarmMonitorProblem(live) {
  if (!live.alarmConnected || live.alarms?.error) return 'alarmUnavailable';
  return live.alarms?.evaluation_stale ? 'alarmEvaluationStale' : null;
}

function alarmSnapshotMatchesProject(live) {
  const sampled = live.alarms?.sampled_revision;
  return sampled === undefined || live.activeRevision == null || sampled === live.activeRevision;
}

export function alarmEvaluationPending(live) {
  return !alarmSnapshotMatchesProject(live)
    || (live.project?.alarms || []).some(alarm => alarm.enabled && !live.alarms?.states?.[alarm.id]?.quality);
}

export function unavailableAlarmTriggers(live) {
  if (!alarmSnapshotMatchesProject(live)) return [];
  const states = live.alarms?.states;
  return (live.project?.alarms || []).filter(alarm => alarm.enabled && states?.[alarm.id]?.quality === 'bad');
}

const routeNeedsAttention = new Set([
  'routeScanOverdue', 'routeRecovering', 'routeAwaitingData', 'routeDataUnavailable', 'routeRetrying',
]);

export function ConnectionStatus({ details = false }) {
  const live = useContext(Live);
  const ui = useUi();
  const routes = (live.project?.connections || []).map(config => {
    const status = live.connections?.find(item => item.id === config.id);
    const state = !config.enabled ? 'routeDisabled'
      : !live.connected ? 'routeUnknown'
      : live.plcHold ? 'routeHeld'
      : status?.scan_overdue === true ? 'routeScanOverdue'
      : status?.recovering === true ? 'routeRecovering'
      : status?.awaiting_data === true ? 'routeAwaitingData'
      : status?.data_unavailable === true ? 'routeDataUnavailable'
      : status?.connected ? 'routeConnected'
      : status?.error != null ? 'routeRetrying' : 'routeConnecting';
    return { ...config, state };
  });
  const enabled = routes.filter(route => route.enabled);
  const connected = enabled.filter(route => route.state === 'routeConnected').length;
  let summary;
  if (!live.connected) summary = routes.length ? 'runtimeOffline' : 'simulatorOffline';
  else if (!enabled.length) summary = routes.length ? 'plcDisabled' : 'simulatorOnline';
  else if (live.plcHold) summary = 'plcHeld';
  else if (connected === enabled.length) summary = 'plcOnline';
  else if (enabled.some(route => route.state === 'routeScanOverdue')) summary = 'plcScanOverdue';
  else if (enabled.some(route => route.state === 'routeRecovering')) summary = 'plcRecovering';
  else if (enabled.some(route => route.state === 'routeDataUnavailable')) summary = 'plcDataUnavailable';
  else if (enabled.some(route => route.state === 'routeAwaitingData')) summary = 'plcAwaitingData';
  else if (connected > 0) summary = 'plcPartial';
  else summary = enabled.some(route => route.state === 'routeRetrying') ? 'plcOffline' : 'plcConnecting';

  const label = ui(summary, { connected, total: enabled.length });
  if (!details) return <span role="status">{label}</span>;
  if (!routes.length) return <span className="connection" role="status">{label}</span>;
  return <details className="connection route-status">
    <summary><span role="status">{label}</span></summary>
    <div className="route-status-list">
      <strong>{ui(live.connected ? 'runtimeOnline' : 'runtimeOffline')}</strong>
      <ul>{routes.map(route => <li key={route.id}>
        <span>{route.name} · {ui(route.state)}</span>
        {live.diagnosticsPermitted && routeNeedsAttention.has(route.state) && <a
          href={`/diagnostics?${new URLSearchParams({ connection: route.id, quality: 'non-good' })}`}
          target="_blank" rel="noopener" aria-label={ui('routeOpenDiagnostics', { route: route.name })}>
          {ui('routeInspectTags')}
        </a>}
      </li>)}</ul>
    </div>
  </details>;
}
