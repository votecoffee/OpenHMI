import React, { createContext, useContext } from 'react';
import { Live, Quality, ConnectionStatus, alarmMonitorProblem, alarmEvaluationPending, unavailableAlarmTriggers } from './live-quality.jsx';
import { useLocalization, LanguageSelector, alarmMessage } from './localization.jsx';
import { PrioritySymbol } from './alarm-controls.jsx';

export const ScreenControls = createContext([]);

export function ScreenFrame({ children, canvas, title, columns, puck, screen_id = 'overview' }) {
  const live = useContext(Live);
  const { text, ui, language } = useLocalization();
  const plcConfigured = live.project?.connections?.some(connection => connection.enabled);
  const monitor = live.alarms;
  const active = [...(monitor?.annunciated_outstanding || monitor?.outstanding || [])].sort((a, b) => a.priority - b.priority);
  const headline = active[0];
  const headlineMessage = headline && `P${headline.priority} ${alarmMessage(headline, language)}`;
  const monitorProblem = alarmMonitorProblem(live);
  const monitorWarning = monitorProblem && <Quality text={ui(monitorProblem)} />;
  const waiting = !monitorProblem && alarmEvaluationPending(live) && <Quality text={ui('alarmEvaluationWaiting')} />;
  const unavailableCount = monitorProblem ? 0 : unavailableAlarmTriggers(live).length;
  const triggerWarning = unavailableCount > 0 && (puck?.isEditing
    ? <Quality text={ui('alarmUnavailableTriggersCount', { count: unavailableCount })} />
    : <a className="hmi-quality" href="/alarms">
      <span aria-hidden="true">×</span> {ui('alarmUnavailableTriggersCount', { count: unavailableCount })}
    </a>);
  return <section className="hmi-screen">
    <header className="station-header">
      <div className="station-identity"><strong>OpenHMI</strong><span>{ui('localStation')}</span></div>
      <div className="station-title"><div className={`screen-alarm-banner ${headline ? 'has-alarm' : ''}`} aria-label="Screen alarm status">
        {headline ? <><PrioritySymbol priority={headline.priority} />
          <strong>{!puck?.isEditing && headline.occurrence_id
            ? <a className="alarm-headline-link" href={`/alarms?occurrence=${headline.occurrence_id}`}
              aria-label={ui('openAlarmDetails', { message: headlineMessage })}>{headlineMessage}</a>
            : headlineMessage} · {ui(monitorProblem ? 'lastRecordedAlarmCounts' : 'activeAlarms', { active: monitor.annunciated_active_count ?? monitor.active_count, unack: monitor.annunciated_unacknowledged_count ?? monitor.unacknowledged_count })}</strong>
          {monitorWarning}{triggerWarning}{waiting}</> : (monitorWarning || triggerWarning || waiting) ? <>{monitorWarning}{triggerWarning}{waiting}</> :
          (monitor?.shelved_count ? ui('noUnshelvedAlarms') : Object.keys(monitor?.states || {}).length ? ui('noActiveAlarms') : ui('noAlarms'))}
          {!monitorProblem && !!monitor?.shelved_count && <a className="shelved-summary" href="/alarms?shelving=shelved">{ui('shelvedSummary', { count: monitor.shelved_count })}</a>}
      </div><h1>{text(screen_id === 'overview' ? 'screen.title' : `screen.${screen_id}.title`, title)}</h1></div>
      <div className="station-mode"><LanguageSelector /><strong>{plcConfigured ? 'PLC' : ui('simulation')}</strong><ConnectionStatus /></div>
    </header>
    {canvas || <div className="station-workspace"><div className="hmi-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>{children}</div>
      <aside className="station-sidebar" aria-label="State legend"><strong>{ui('state')}</strong><span><i className="binary-symbol legend-on" /> {ui('on')}</span>
        <span><i className="binary-symbol" /> {ui('off')}</span><span className="sidebar-note">{ui('textShape')}</span></aside></div>}
    <footer className="station-footer"><span className="station-location">{screen_id === 'overview' ? ui('overview') : text(`screen.${screen_id}.title`, title)}</span>
      <span className="footer-description">{ui(plcConfigured ? 'localPlcRuntime' : 'localSimulator')}</span>{puck?.isEditing ? <span>{ui('preview')}</span> : <><a href="/alarms">{ui('alarms')}</a><a href="/">{ui('editScreen')}</a></>}</footer>
  </section>;
}
