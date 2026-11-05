import React, { createContext, useContext } from 'react';
import { formatLocalDateTime, useLocalization, useUi } from './localization.jsx';

export const Live = createContext({ values: {}, connected: false });

const problems = {
  held: 'tagHeld', disabled: 'tagDisabled', disconnected: 'tagPlcOffline',
  recovering: 'tagRecovering', pending: 'tagWaiting', stale: 'tagStale',
};

export function tagQuality(live, tag) {
  if (!live.connected) return 'commLoss';
  const sample = live.samples?.[tag];
  if (sample) return sample.quality === 'good' ? null : problems[sample.quality_reason || sample.quality] || 'badData';
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

export function Quality({ problem, tag, text }) {
  const live = useContext(Live);
  const { language } = useLocalization() || { language: { code: 'en' } };
  const ui = useUi();
  const sample = live.samples?.[tag];
  const age = sample?.age_seconds;
  const sourceTime = sample?.timestamp && new Date(sample.timestamp);
  const ageText = Number.isFinite(age) ? ui('tagSampleAge', { age: age.toFixed(1) }) : '';
  const label = text ?? ui(problem);
  const title = [label, sample?.error, ageText, sourceTime && formatLocalDateTime(sourceTime, language.code)]
    .filter(Boolean).join(' · ');
  return <span className="hmi-quality" title={title}><span aria-hidden="true">×</span> {label}
    {problem === 'tagStale' && ageText && <small>{ageText}</small>}
  </span>;
}

export function ConnectionStatus({ details = false }) {
  const live = useContext(Live);
  const ui = useUi();
  const routes = (live.project?.connections || []).map(config => {
    const status = live.connections?.find(item => item.id === config.id);
    const state = !config.enabled ? 'routeDisabled'
      : !live.connected ? 'routeUnknown'
      : live.plcHold ? 'routeHeld'
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
  else if (connected > 0) summary = 'plcPartial';
  else summary = enabled.some(route => route.state === 'routeRetrying') ? 'plcOffline' : 'plcConnecting';

  const label = ui(summary, { connected, total: enabled.length });
  if (!details) return <span role="status">{label}</span>;
  if (!routes.length) return <span className="connection" role="status">{label}</span>;
  return <details className="connection route-status">
    <summary><span role="status">{label}</span></summary>
    <div className="route-status-list">
      <strong>{ui(live.connected ? 'runtimeOnline' : 'runtimeOffline')}</strong>
      <ul>{routes.map(route => <li key={route.id}>{route.name} · {ui(route.state)}</li>)}</ul>
    </div>
  </details>;
}
