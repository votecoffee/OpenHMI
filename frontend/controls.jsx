import React, { createContext, useContext, useEffect, useState } from 'react';
import { Live, useValue, tagValue, Quality, ConnectionStatus, alarmMonitorProblem, alarmEvaluationPending, unavailableAlarmTriggers } from './live-quality.jsx';
import { api, json } from './api.mjs';
import { isCommandPage, isCommandRecord } from './command-status.mjs';
import { controlTypes } from './model.mjs';
import { useLocalization, useUi, LanguageSelector, alarmMessage } from './localization.jsx';
import { LoadedRecipe } from './recipes.jsx';
import { SecurityContext, allowed, SecurityLock, CurrentUser } from './security.jsx';

import { WebBrowser } from './web-browser.jsx';
import { EditControl } from './edit-control.jsx';
import { ChoiceFields, DiscreteInput } from './discrete-input.jsx';
import { MultiState, ModeSelector, PermissiveList, StateFields, PermissiveFields } from './machine-state.jsx';
import { Trend, TrendFields } from './trend.jsx';
import { TrendRecordingFields } from './trend-recording.jsx';
import { ChartFields, ProcessChart, TankGraphic, chartSeries } from './charts.jsx';

export const ScreenControls = createContext([]);

function TagReference({ tag, puck }) {
  return puck?.isEditing ? <span className="hmi-source">{tag}</span> : null;
}

export function PrioritySymbol({ priority }) {
  // Independent SVG shapes follow the ME palette's number/shape/color vocabulary.
  const shapes = {
    1: <rect x="2" y="2" width="28" height="28" />,
    2: <polygon points="9,2 23,2 31,16 23,30 9,30 1,16" />,
    3: <polygon points="16,1 31,30 1,30" />,
    4: <polygon points="16,1 31,12 25,30 7,30 1,12" />,
  };
  return <svg className={`priority-symbol priority-${priority}`} viewBox="0 0 32 32" aria-hidden="true">
    {shapes[priority]}<text x="16" y={priority === 3 ? 24 : 21} textAnchor="middle">{priority}</text>
  </svg>;
}

function NumericDisplay({ id, label, tag, unit, decimals, puck }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, language } = useLocalization();
  let formatted;
  try { formatted = valid ? new Intl.NumberFormat(language.code, { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: false }).format(value) : ''; }
  catch { formatted = valid ? value.toFixed(decimals) : ''; }
  return <article className="hmi-control hmi-numeric" data-control="numeric">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {valid ? <strong className="hmi-value">{formatted} <small>{text(`control.${id}.unit`, unit)}</small></strong> : <Quality problem={problem} tag={tag} />}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

const annotationSymbols = {
  arrow: { label: 'Arrow', path: 'M4 12h15m-6-6 6 6-6 6' },
  info: { label: 'Information', path: 'M12 11v6m0-10v.2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z' },
  warning: { label: 'Warning', path: 'M12 3 22 21H2zm0 7v4m0 3v.2' },
  check: { label: 'Check mark', path: 'm4 12 5 5L20 6' },
  circle: { label: 'Circle', path: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z' },
  diamond: { label: 'Diamond', path: 'm12 2 10 10-10 10L2 12z' },
};

function StaticLabel({ id, label, font_size, alignment, weight }) {
  const { text } = useLocalization();
  return <div className="hmi-annotation hmi-static-label" data-control="label"
    style={{ fontSize: font_size, textAlign: alignment, fontWeight: weight }}>
    {text(`control.${id}.label`, label)}
  </div>;
}

function ScreenSymbol({ id, label, symbol, size, rotation }) {
  const { text } = useLocalization();
  return <div className="hmi-annotation hmi-symbol" data-control="symbol">
    <svg role="img" aria-label={text(`control.${id}.label`, label)} viewBox="0 0 24 24" width={size} height={size}
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={annotationSymbols[symbol]?.path} transform={`rotate(${rotation} 12 12)`} />
    </svg>
  </div>;
}

function ProgressBar({ id, label, tag, unit, decimals, minimum, maximum, puck }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, ui } = useLocalization();
  const title = text(`control.${id}.label`, label);
  const reading = valid ? `${value.toFixed(decimals)} ${text(`control.${id}.unit`, unit)}`.trim() : '';
  const span = maximum - minimum;
  const outside = valid && (value < minimum || value > maximum);
  return <article className="hmi-control hmi-progress" data-control="progress">
    <span className="hmi-label">{title}</span>
    {valid ? <strong className="hmi-value">{reading}</strong> : <Quality problem={problem} tag={tag} />}
    {!(0 < span && Number.isFinite(span)) ? <Quality problem="badRange" /> : valid && <>
      <progress aria-label={title} aria-valuetext={reading} max={1}
        value={Math.max(0, Math.min(1, (value - minimum) / span))} />
      <div className="analog-scale"><span>{minimum}</span>
        {outside && <strong>{ui('outOfScale')}</strong>}<span>{maximum}</span></div>
    </>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function TextDisplay({ id, label, tag, puck }) {
  const { value, valid, problem } = useValue(tag, 'string');
  const { text } = useLocalization();
  return <article className="hmi-control" data-control="text">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {valid ? <strong className="hmi-text-value">{value}</strong> : <Quality problem={problem} tag={tag} />}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function Indicator({ id, label, tag, on_text = 'ON', off_text = 'OFF', puck }) {
  const { value, valid, problem } = useValue(tag, 'boolean');
  const { text } = useLocalization();
  return <article className="hmi-control hmi-indicator" data-control="indicator">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {valid ? <strong className={`hmi-state ${value ? 'is-on' : ''}`}>
      <span className="binary-symbol" aria-hidden="true" />{value ? text(`control.${id}.on_text`, on_text) : text(`control.${id}.off_text`, off_text)}
    </strong> : <Quality problem={problem} tag={tag} />}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function AnalogRange({ id, label, tag, unit, decimals, minimum, maximum, normal_low, normal_high, puck, tank = false }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, ui, language } = useLocalization();
  label = text(`control.${id}.label`, label);
  unit = text(`control.${id}.unit`, unit);
  let formatted;
  try { formatted = valid ? new Intl.NumberFormat(language.code, { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: false }).format(value) : ''; }
  catch { formatted = valid ? value.toFixed(decimals) : ''; }
  const configured = [minimum, maximum, normal_low, normal_high].every(Number.isFinite)
    && Number.isFinite(maximum - minimum) && minimum <= normal_low && normal_low < normal_high && normal_high <= maximum;
  const position = number => Math.max(0, Math.min(100, (number - minimum) / (maximum - minimum) * 100));
  const outside = valid && (value < minimum || value > maximum);
  const graphicLabel = valid ? `${label}: ${value} ${unit}, scale ${minimum} to ${maximum}, normal ${normal_low} to ${normal_high}${outside ? ', out of scale' : ''}` : `${label}: ${ui(problem)}`;
  return <article className="hmi-control hmi-analog" data-control={tank ? 'tank' : 'analog'}>
    <div className="analog-heading"><span className="hmi-label">{label}</span>
      {valid ? <strong className="hmi-value">{formatted} <small>{unit}</small></strong> : <Quality problem={problem} tag={tag} />}</div>
    {!configured ? <Quality problem="badRange" /> : <>
      {tank ? <TankGraphic label={graphicLabel} position={valid ? position(value) : 0} valid={valid} minimum={minimum} maximum={maximum}
        normalLow={position(normal_low)} normalHigh={position(normal_high)} />
        : <div className={`analog-track ${!valid ? 'invalid' : ''}`} role="img" aria-label={graphicLabel}>
        <span className="normal-band" style={{ left: `${position(normal_low)}%`, width: `${position(normal_high) - position(normal_low)}%` }} />
        {valid && <span className="analog-pointer" style={{ left: `${position(value)}%` }} aria-hidden="true">▼</span>}
      </div>}
      <div className="analog-scale">{!tank && <span>{minimum}</span>}<span>{ui('normal')} {normal_low}–{normal_high} {unit}</span>{!tank && <span>{maximum}</span>}</div>
      {valid && (outside || value < normal_low || value > normal_high) && <strong className="range-deviation">{outside ? ui('outOfScale') : ui('outsideBand')}</strong>}
    </>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function AlarmIndicator({ id, label, tag, priority, puck }) {
  const { value, valid, problem } = useValue(tag, 'boolean');
  const { text, ui } = useLocalization();
  return <article className={`hmi-control hmi-alarm ${valid && value ? 'alarm-active' : ''}`} data-control="alarm">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {!valid ? <Quality problem={problem} tag={tag} /> : value ? <strong className="alarm-state"><PrioritySymbol priority={priority} />P{priority} {ui('active')}</strong>
      : <span className="alarm-inactive">{ui('inactive')}</span>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function ActionButton({ id, label, action, mode = 'python', command = '', target = '', security_groups = [], puck, enabled_tag = '' }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const definition = mode === 'command' ? live.project?.commands?.find(item => item.id === command) : null;
  const permitted = allowed(session, 'runtime.operate', security_groups) && (mode !== 'command' || !!definition && allowed(session, 'runtime.operate', definition.security_groups));
  const { text, ui } = useLocalization();
  const targetTag = mode === 'command' ? definition?.root_tag : ['set', 'toggle'].includes(mode) ? target : '';
  const permitTag = definition?.permit_member ? definition.root_tag + '.' + definition.permit_member : '';
  const enabled = enabled_tag ? tagValue(live, enabled_tag, 'boolean') : null;
  const permit = permitTag ? tagValue(live, permitTag, 'boolean') : null;
  const targetState = targetTag ? tagValue(live, targetTag, mode === 'toggle' ? 'boolean' : undefined) : null;
  const unavailableBinding = [
    { state: enabled, tag: enabled_tag, label: 'editEnableBinding' },
    { state: permit, tag: permitTag, label: 'actionPermitBinding' },
    { state: targetState, tag: targetTag, label: mode === 'command' ? 'actionCommandBinding' : 'actionTargetBinding' },
  ].find(binding => binding.state?.problem);
  const unavailable = !live.connected ? 'commLoss' : unavailableBinding?.state.problem;
  const unavailableLabel = unavailableBinding ? ui('editBindingProblem', {
    binding: ui(unavailableBinding.label), quality: ui(unavailable),
  }) : undefined;
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [failed, setFailed] = useState(false);
  const [latest, setCommandStatus] = useState(null);
  const commandStatus = latest?.command === command ? latest : null;
  const transaction = commandStatus?.transaction;
  const commandBlocked = mode === 'command' && (!commandStatus?.available
    || ['prepared', 'staging', 'requested', 'accepted', 'uncertain'].includes(transaction?.state));
  useEffect(() => {
    if (mode !== 'command' || puck?.isEditing || !permitted) { setCommandStatus(null); return; }
    if (busy) return;
    let stopped = false, timer;
    async function refresh() {
      try {
        const data = await api(`/api/commands?command_id=${encodeURIComponent(command)}&limit=1`);
        if (!isCommandPage(data) || data.items.length > 1 || data.items.some(item => item.command_id !== command)) {
          throw new Error('Invalid command status response');
        }
        const next = data.items[0] ?? null;
        if (!stopped) setCommandStatus(previous => {
          const known = previous?.command === command ? previous.transaction : null;
          return known && (!next || known.id > next.id)
            ? { command, available: false, transaction: known }
            : { command, available: true, transaction: next };
        });
      } catch (error) {
        const denied = [401, 403].includes(error.status);
        if (!stopped) setCommandStatus(previous => ({ command, available: false,
          transaction: !denied && previous?.command === command ? previous.transaction : null }));
      }
      if (!stopped) timer = setTimeout(refresh, 1000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [command, mode, permitted, puck?.isEditing, busy]);
  async function invoke(event) {
    const opener = event.currentTarget;
    setBusy(true);
    setFailed(false);
    try {
      const result = await api(`/api/controls/${encodeURIComponent(id)}/activate`,
        json('POST', { expected_revision: live.activeRevision }));
      if (mode === 'command') {
        if (!isCommandRecord(result?.transaction) || result.transaction.command_id !== command) {
          throw new Error(ui('commandStatusUnavailable'));
        }
        setCommandStatus({ command, available: null, transaction: result.transaction });
      }
      if (result.mode) window.dispatchEvent(new CustomEvent('openhmi-navigate', { detail: { ...result, opener } }));
      setFeedback(result.transaction ? `Request dispatched. Transaction ${result.transaction.id}${result.audit_status === 'pending' ? `; activity finalization pending. Operation ${result.operation_id}` : ''}` : result.audit_status === 'pending' ? `Completed; activity finalization pending. Operation ${result.operation_id}` : ui('completed'));
    } catch (error) {
      if (mode === 'command') setCommandStatus(previous => ({ command, available: false,
        transaction: ![401, 403].includes(error.status) && previous?.command === command ? previous.transaction : null }));
      setFeedback(error.message); setFailed(true);
    } finally { setBusy(false); }
  }
  return <article className="hmi-control hmi-command security-protected" data-control="button">
    <button className="hmi-action" disabled={puck?.isEditing || !!unavailable || busy || !permitted || !!enabled && enabled.value !== true || !!permit && permit.value !== true || commandBlocked} onClick={invoke}>
      {busy ? ui('working') : text(`control.${id}.label`, label)}
    </button><span className={failed ? 'hmi-quality' : 'command-feedback'}>
      {busy ? ui('pending') : puck?.isEditing ? ui('configureAction') : feedback || (!permitted ? 'Sign in with an authorized HMI group' : '')}
    </span>
    {unavailable && !puck?.isEditing && <Quality problem={unavailable} tag={unavailableBinding?.tag} text={unavailableLabel} />}
    {!puck?.isEditing && enabled?.valid && enabled.value === false && <small>{ui('editEnableOff', { tag: enabled_tag })}</small>}
    {!puck?.isEditing && permit?.valid && permit.value === false && <small>{ui('actionPermitOff', { tag: permitTag })}</small>}
    {!permitted && !puck?.isEditing && <SecurityLock label={label} permission="runtime.operate" groups={security_groups} additionalGroups={definition?.security_groups || []} />}
    {mode === 'command' && permitted && !puck?.isEditing && !busy && !commandStatus?.available &&
      <span className="hmi-quality" role="status">{ui(commandStatus?.available === false ? 'commandStatusUnavailable' : 'commandStatusWaiting')}</span>}
    {mode === 'command' && permitted && !puck?.isEditing && transaction && <>
      <span className="command-feedback" role="status">PLC command: {transaction.state} · sequence {transaction.sequence}{transaction.result_code !== null ? ` · result ${transaction.result_code}` : ''}</span>
      <a className="command-transaction-link" href={`/commands?transaction=${transaction.id}`}>{ui('viewCommandTransaction', { id: transaction.id })}</a>
    </>}
  </article>;
}

function NumericInput(props) { return <EditControl {...props} />; }
function TextInput(props) { return <EditControl {...props} text />; }
function TextArea(props) { return <EditControl {...props} text multiline />; }
function BarcodeInput(props) { return <EditControl {...props} text barcode />; }

function SelectedRecipe({ id, label }) {
  const { text } = useLocalization();
  return <article className="hmi-control hmi-recipe" data-control="recipe"><span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    <LoadedRecipe compact /></article>;
}

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

function Conditional({ children, visible_tag, enabled_tag, color_tag, active_color, puck }) {
  const live = useContext(Live);
  const ui = useUi();
  const isTrue = tag => { const state = tagValue(live, tag, 'boolean'); return state.valid && state.value; };
  if (!puck?.isEditing && visible_tag && !isTrue(visible_tag)) return null;
  const enabled = !puck?.isEditing && enabled_tag ? tagValue(live, enabled_tag, 'boolean') : null;
  const disabled = enabled != null && (!enabled.valid || enabled.value !== true);
  return <div className="binding-frame" style={color_tag && isTrue(color_tag) ? { '--hmi-live': active_color, '--hmi-annotation-color': active_color } : {}}>
    {disabled && (enabled.valid ? <small>{ui('editEnableOff', { tag: enabled_tag })}</small>
      : <Quality tag={enabled_tag} problem={enabled.problem}
        text={ui('editBindingProblem', { binding: ui('editEnableBinding'), quality: ui(enabled.problem) })} />)}
    <fieldset className="binding-contents" disabled={disabled}>{children}</fieldset>
  </div>;
}

function LiveTrend(props) {
  const live = useContext(Live);
  return <Trend {...props} live={live} />;
}

function LiveChart(props) {
  const live = useContext(Live);
  return <ProcessChart {...props} live={live} />;
}

export function createConfig(catalog) {
  const groupsField = { type: 'custom', render: ({ value = [], onChange }) => <fieldset className="security-group-choice"><legend>Allowed HMI groups (any selected)</legend>
    {catalog.security_groups.map(group => <label key={group}><input type="checkbox" checked={value.includes(group)} onChange={event => onChange(event.target.checked ? [...value, group] : value.filter(item => item !== group))} />{group}</label>)}
    <small>No groups selected: use the user's operation permission.</small></fieldset> };
  const tagField = type => ({ type: 'select', label: 'Tag', options: catalog.tags
    .filter(tag => tag.type === type).map(tag => ({ label: tag.name, value: tag.name })) });
  const browserTag = (label, unbound, predicate) => ({ type: 'select', label, options: [
    { label: unbound, value: '' }, ...catalog.tags.filter(predicate).map(tag => ({ label: tag.name, value: tag.name })),
  ] });
  const limitTag = label => ({ type: 'select', label, options: [{ label: 'Fixed HMI value', value: '' }, ...catalog.tags.filter(tag => tag.type === 'number').map(tag => ({ label: tag.name, value: tag.name }))] });
  const labelField = { type: 'text', label: 'Label' };
  const integerTag = tag => tag.integer && tag.unscaled !== false;
  const requestedTag = tag => integerTag(tag) && tag.writable;
  const writableText = tag => tag.writable && tag.type === 'string';
  const writableBoolean = tag => tag.writable && tag.type === 'boolean';
  const writableChoice = tag => requestedTag(tag) || writableText(tag);
  const discrete = (kind, label, predicate, choice = false) => {
    const tag = catalog.tags.find(predicate);
    const values = tag?.type === 'string' ? ['0', '1'] : [0, 1];
    return {
      label, fields: { label: labelField, tag: browserTag('Tag', 'Choose a writable tag', predicate),
        security_groups: groupsField, ...(choice ? { options: { type: 'custom', render: ({ value, onChange }) =>
          <ChoiceFields value={value} onChange={onChange} /> } } : {}) },
      defaultProps: { label, tag: tag?.name || '', security_groups: [],
        ...(choice ? { options: values.map((value, index) => ({ value, label: 'Choice ' + (index + 1) })) } : {}) },
      render: props => <DiscreteInput {...props} kind={kind} />,
    };
  };
  const statesField = { type: 'custom', render: ({ value, onChange }) => <StateFields value={value} onChange={onChange} /> };
  const defaultStates = [
    { value: 0, label: 'Stopped', symbol: 'square', color: '#555555' },
    { value: 1, label: 'Running', symbol: 'circle', color: '#333333' },
  ];
  const numericFields = { label: labelField, tag: tagField('number'), unit: { type: 'text', label: 'Units' },
    decimals: { type: 'select', label: 'Decimal places', options: [0, 1, 2, 3, 4].map(value => ({ label: String(value), value })) } };
  const textFields = { label: labelField, tag: tagField('string'),
    min_length: { type: 'number', label: 'Minimum length' }, max_length: { type: 'number', label: 'Maximum length' },
    min_length_tag: limitTag('Minimum length from tag'), max_length_tag: limitTag('Maximum length from tag'), security_groups: groupsField };
  const textDefaults = { label: 'Operator text', tag: 'OperatorText', min_length: 0, max_length: 82, security_groups: [] };
  const numericEditFields = { ...numericFields, minimum: { type: 'number', label: 'Minimum' },
    maximum: { type: 'number', label: 'Maximum' }, minimum_tag: limitTag('Minimum from tag'),
    maximum_tag: limitTag('Maximum from tag'), security_groups: groupsField };
  const sliderTag = tag => tag.type === 'number' && tag.writable && (!tag.integer || tag.unscaled !== false);
  const numericDefaults = { label: 'Tank level', tag: 'TankLevel', unit: '%', decimals: 1 };
  const scaleFields = { minimum: { type: 'number', label: 'Scale minimum' }, maximum: { type: 'number', label: 'Scale maximum' } };
  const analogFields = { ...numericFields, ...scaleFields,
    normal_low: { type: 'number', label: 'Normal low' }, normal_high: { type: 'number', label: 'Normal high' } };
  const analogDefaults = { ...numericDefaults, minimum: 0, maximum: 100, normal_low: 20, normal_high: 80 };
  const chartField = radar => ({ type: 'custom', render: ({ value, onChange }) =>
    <ChartFields value={value} onChange={onChange} catalog={catalog} radar={radar} /> });
  const conditionTag = label => ({ type: 'select', label, options: [{ label: 'Always / none', value: '' }, ...catalog.tags.filter(tag => tag.type === 'boolean').map(tag => ({ label: tag.name, value: tag.name }))] });
  const commonFields = { visible_tag: conditionTag('Visible when tag is true'), enabled_tag: conditionTag('Enabled when tag is true'), color_tag: conditionTag('Color when tag is true'), active_color: { type: 'select', label: 'Active value color', options: [['#002878', 'Navy'], ['#333333', 'Dark gray'], ['#fa3232', 'Priority 1 red'], ['#fff546', 'Priority 2 yellow'], ['#ff9600', 'Priority 3 orange'], ['#ff64c8', 'Priority 4 magenta']].map(([value, label]) => ({ value, label })) } };
  const displayTypes = ['StaticLabel', 'ScreenSymbol', 'ProgressBar'];
  const chartTypes = ['TankLevel', 'BarGraph', 'RadarChart'];
  const inputTypes = ['NumericInput', 'Slider', 'TextInput', 'TextArea', 'BarcodeInput', 'Dropdown', 'RadioGroup', 'Checkbox', 'ToggleSwitch'];
  const config = {
    root: {
      fields: { title: { type: 'text', label: 'Screen name' }, columns: { type: 'select', label: 'Columns',
        options: [1, 2, 3].map(value => ({ label: String(value), value })) } },
      defaultProps: { title: 'Station overview', columns: 2 }, render: ScreenFrame,
    },
    categories: {
      hmi: { title: 'High performance HMI', components: Object.values(controlTypes)
        .filter(type => !chartTypes.includes(type) && !inputTypes.includes(type) && !displayTypes.includes(type) && (type !== 'Faceplate' || catalog.faceplates?.length)) },
      inputs: { title: 'Inputs', components: inputTypes },
      display: { title: 'Display', components: displayTypes },
      charts: { title: 'Live charts', components: chartTypes },
    },
    components: {
      Trend: { label: 'Trend', fields: {
        label: labelField, seconds: { type: 'number', label: 'Time window (seconds)', min: 10, max: 604800 },
        pens: { type: 'custom', render: ({ value, onChange }) => <TrendFields value={value} onChange={onChange} catalog={catalog} /> },
        recording: { type: 'custom', render: ({ value, onChange }) => <TrendRecordingFields value={value} onChange={onChange} catalog={catalog} /> },
      }, defaultProps: { label: 'Process trend', pens: { tags: ['TankLevel'], series: {} }, seconds: 300 },
      render: props => <LiveTrend {...props} catalog={catalog} /> },
      WebBrowser: { label: 'Web Browser / Camera View', fields: {
        label: labelField,
        scheme: { type: 'select', label: 'Scheme', options: [{ label: 'HTTPS', value: 'https' }, { label: 'HTTP', value: 'http' }] },
        hosts: { type: 'text', label: 'Approved hosts (comma-separated)' },
        port: { type: 'number', label: 'Port (blank uses scheme default)', min: 1, max: 65535 },
        path: { type: 'text', label: 'Approved path' },
        address_tag: browserTag('Address from tag', 'Fixed address (first approved host)', tag => tag.type === 'string'),
        refresh_tag: browserTag('Refresh from tag', 'Manual refresh only', tag => tag.type === 'boolean' || tag.integer),
      }, defaultProps: { label: 'Camera view', scheme: 'https', hosts: '', port: null, path: '/', address_tag: '', refresh_tag: '' },
      render: WebBrowser },
      Faceplate: { label: 'UDT faceplate', fields: { label: labelField, template: { type: 'select', label: 'Definition', options: (catalog.faceplates || []).map(item => ({ label: item.name, value: item.id })) }, root_tag: tagField('struct') },
        defaultProps: { label: 'Equipment', template: catalog.faceplates?.[0]?.id || '', root_tag: catalog.tags.find(tag => tag.type === 'struct')?.name || '' },
        render: props => <FaceplateInstance {...props} config={config} /> },
      MultiState: { label: 'Multi-state indicator', fields: {
        label: labelField, tag: browserTag('State tag', 'Choose an integer tag', integerTag), states: statesField,
      }, defaultProps: { label: 'Machine state', tag: 'AlarmWord', states: defaultStates }, render: MultiState },
      ModeSelector: { label: 'Mode selector', fields: {
        label: labelField, tag: browserTag('Mode request tag', 'Choose a writable integer tag', requestedTag),
        confirmed_tag: browserTag('PLC confirmed mode tag', 'Choose a separate integer tag', integerTag),
        states: statesField, security_groups: groupsField,
        presentation: { type: 'select', label: 'Presentation', options: [
          { label: 'Dropdown', value: 'dropdown' }, { label: 'Segmented buttons', value: 'segments' },
        ] },
      }, defaultProps: { label: 'Machine mode', tag: catalog.tags.find(requestedTag)?.name || '', confirmed_tag: '',
        states: [{ ...defaultStates[0], label: 'Manual' }, { ...defaultStates[1], label: 'Auto' }],
        presentation: 'dropdown', security_groups: [] }, render: ModeSelector },
      PermissiveList: { label: 'Permissive / interlock list', fields: {
        label: labelField, checks: { type: 'custom', render: ({ value, onChange }) =>
          <PermissiveFields value={value} onChange={onChange} catalog={catalog} /> },
      }, defaultProps: { label: 'Start permissives', checks: [{ tag: 'MotorRunning', label: 'Motor running', expected: false }] },
      render: PermissiveList },
      NumericInput: { label: 'Numeric input', fields: numericEditFields,
        defaultProps: { ...numericDefaults, label: 'Tank setpoint', minimum: 0, maximum: 100, security_groups: [] }, render: NumericInput },
      Slider: { label: 'Slider', fields: { ...numericEditFields, tag: browserTag('Tag', 'Choose a writable numeric tag', sliderTag) },
        defaultProps: { ...numericDefaults, label: 'Setpoint slider', unit: '', tag: catalog.tags.find(sliderTag)?.name || '',
          minimum: 0, maximum: 100, security_groups: [] },
        render: props => <EditControl {...props} slider sliderInteger={!!catalog.tags.find(tag => tag.name === props.tag)?.integer} /> },
      StaticLabel: { label: 'Static label', fields: {
        label: labelField, font_size: { type: 'number', label: 'Font size (px)', min: 8, max: 72 },
        alignment: { type: 'select', label: 'Text alignment', options: [
          { label: 'Start', value: 'start' }, { label: 'Center', value: 'center' }, { label: 'End', value: 'end' },
        ] },
        weight: { type: 'select', label: 'Text weight', options: [
          { label: 'Normal', value: 'normal' }, { label: 'Bold', value: 'bold' },
        ] },
      }, defaultProps: { label: 'Machine section', font_size: 16, alignment: 'start', weight: 'normal' }, render: StaticLabel },
      ScreenSymbol: { label: 'Symbol', fields: {
        label: { type: 'text', label: 'Accessible label' },
        symbol: { type: 'select', label: 'Shape', options: Object.entries(annotationSymbols)
          .map(([value, { label }]) => ({ value, label })) },
        size: { type: 'number', label: 'Symbol size (px)', min: 12, max: 96 },
        rotation: { type: 'select', label: 'Rotation', options: [0, 90, 180, 270]
          .map(value => ({ value, label: String(value) + ' degrees' })) },
      }, defaultProps: { label: 'Direction of travel', symbol: 'arrow', size: 28, rotation: 0 }, render: ScreenSymbol },
      ProgressBar: { label: 'Progress bar', fields: { ...numericFields, ...scaleFields },
        defaultProps: { ...numericDefaults, label: 'Progress', minimum: 0, maximum: 100 }, render: ProgressBar },
      CurrentUser: { label: 'Current login user', fields: { label: labelField }, defaultProps: { label: 'Current user' }, render: CurrentUser },
      TextDisplay: { label: 'Text display', fields: { label: labelField, tag: tagField('string') },
        defaultProps: { label: 'Status text', tag: 'OperatorText' }, render: TextDisplay },
      TextInput: { label: 'Text input', fields: textFields, defaultProps: textDefaults, render: TextInput },
      TextArea: { label: 'Text area', fields: { ...textFields, tag: browserTag('Tag', 'Choose a writable text tag', writableText) },
        defaultProps: { ...textDefaults, label: 'Operator notes', tag: catalog.tags.find(writableText)?.name || '' }, render: TextArea },
      BarcodeInput: { label: 'Barcode scanner input', fields: { ...textFields, tag: browserTag('Tag', 'Choose a writable text tag', writableText) },
        defaultProps: { ...textDefaults, label: 'Barcode', tag: catalog.tags.find(writableText)?.name || '', min_length: 1 }, render: BarcodeInput },
      Dropdown: discrete('dropdown', 'Dropdown', writableChoice, true),
      RadioGroup: discrete('radio_group', 'Radio group', writableChoice, true),
      Checkbox: discrete('checkbox', 'Checkbox', writableBoolean),
      ToggleSwitch: discrete('toggle_switch', 'Toggle switch', writableBoolean),
      SelectedRecipe: { label: 'Selected recipe', fields: { label: labelField }, defaultProps: { label: 'Loaded recipe' }, render: SelectedRecipe },
      NumericDisplay: { label: 'Numeric display', fields: numericFields, defaultProps: numericDefaults, render: NumericDisplay },
      Indicator: {
        label: 'Indicator', fields: { label: labelField, tag: tagField('boolean'), on_text: { type: 'text', label: 'ON text' }, off_text: { type: 'text', label: 'OFF text' } },
        defaultProps: { label: 'Motor', tag: 'MotorRunning', on_text: 'ON', off_text: 'OFF' }, render: Indicator,
      },
      AnalogRange: { label: 'Analog range', fields: analogFields,
        defaultProps: { ...analogDefaults, label: 'Tank operating range' }, render: AnalogRange },
      TankLevel: { label: 'Tank level indicator', fields: analogFields,
        defaultProps: analogDefaults, render: props => <AnalogRange {...props} tank /> },
      BarGraph: { label: 'Bar graph', fields: { label: labelField, ...scaleFields, unit: numericFields.unit, series: chartField(false) },
        defaultProps: { label: 'Process comparison', minimum: 0, maximum: 100, unit: '', series: [chartSeries('TankLevel', false)] },
        render: LiveChart },
      RadarChart: { label: 'Radar chart', fields: { label: labelField, series: chartField(true) },
        defaultProps: { label: 'Process profile', series: catalog.tags.filter(tag => tag.type === 'number').slice(0, 3).map(tag => chartSeries(tag.name, true)) },
        render: props => <LiveChart {...props} radar /> },
      AlarmIndicator: {
        label: 'Alarm indicator', fields: { label: labelField, tag: tagField('boolean'), priority: { type: 'select', label: 'Alarm priority',
          options: [1, 2, 3, 4].map(value => ({ label: `Priority ${value}`, value })) } },
        defaultProps: { label: 'Process alarm', tag: 'ProcessAlarm', priority: 2 }, render: AlarmIndicator,
      },
      ActionButton: {
        label: 'Action button', fields: { label: labelField, security_groups: groupsField,
          mode: { type: 'select', label: 'Action type', options: [['python', 'Python action'], ['command', 'PLC command transaction'], ['set', 'Set tag'], ['toggle', 'Toggle Boolean tag'], ['navigate', 'Navigate to screen'], ['popup', 'Open popup'], ['close_popup', 'Close popup']].map(([value, label]) => ({ value, label })) },
          command: { type: 'select', label: 'PLC command contract', options: (catalog.commands || []).map(item => ({ label: item.name, value: item.id })) },
          target: { type: 'select', label: 'Target tag', options: catalog.tags.filter(tag => tag.type !== 'struct').map(tag => ({ label: tag.name, value: tag.name })) },
          value: { type: 'custom', render: ({ value = false, onChange }) => <fieldset><legend>Value to write</legend><select aria-label="Action value type" value={typeof value} onChange={event => onChange(event.target.value === 'boolean' ? false : event.target.value === 'number' ? 0 : '')}><option value="boolean">Boolean</option><option value="number">Number</option><option value="string">Text</option></select>{typeof value === 'boolean' ? <label><input type="checkbox" checked={value} onChange={event => onChange(event.target.checked)} />True</label> : <input aria-label="Action value" type={typeof value === 'number' ? 'number' : 'text'} value={value} onChange={event => onChange(typeof value === 'number' ? Number(event.target.value) : event.target.value)} />}</fieldset> },
          screen: { type: 'select', label: 'Target screen / popup', options: (catalog.screens || [{ id: 'overview', title: 'Overview' }]).map(screen => ({ label: `${screen.title}${screen.popup ? ' (popup)' : ''}`, value: screen.id })) },
          action: { type: 'select', label: 'Python action',
          options: catalog.actions.map(action => ({ label: action.label, value: action.name })) } },
        defaultProps: { label: 'Toggle simulated motor', action: 'toggle_motor', security_groups: [], mode: 'python', target: 'MotorRunning', value: false, screen: 'overview' }, render: ActionButton,
      },
    },
  };
  for (const component of Object.values(config.components)) {
    component.fields = { ...component.fields, ...commonFields };
    const renderer = component.render;
    const handlesOwnEnable = renderer === NumericInput || renderer === TextInput || renderer === TextArea || renderer === BarcodeInput || renderer === ActionButton || component === config.components.Slider;
    component.render = props => <Conditional {...props} enabled_tag={handlesOwnEnable ? '' : props.enabled_tag}>
      {renderer(props)}
    </Conditional>;
  }
  if (!catalog.faceplates?.length) delete config.components.Faceplate;
  return config;
}

function FaceplateInstance({ id, label, template, root_tag, puck, config, enabled_tag }) {
  const live = useContext(Live);
  const { text } = useLocalization();
  const definition = live.project?.faceplates?.find(item => item.id === template);
  if (!definition) return <article className="hmi-control" data-control="faceplate"><strong>{label}</strong><p>Faceplate definition unavailable</p></article>;
  return <article className="hmi-faceplate" data-control="faceplate"><strong>{text(`control.${id}.label`, label)}</strong><div className="faceplate-grid">{definition.controls.map(control => {
    const resolved = { ...control, id: `${id}__${control.id}`, puck, instance_enabled_tag: enabled_tag };
    for (const field of ['tag', 'target', 'visible_tag', 'enabled_tag', 'color_tag',
      'minimum_tag', 'maximum_tag', 'min_length_tag', 'max_length_tag', 'address_tag', 'refresh_tag', 'confirmed_tag']) {
      if (resolved[field]?.startsWith('$.')) resolved[field] = root_tag + resolved[field].slice(1);
    }
    if (resolved.checks) resolved.checks = resolved.checks.map(check =>
      check.tag.startsWith('$.') ? { ...check, tag: root_tag + check.tag.slice(1) } : check);
    if (resolved.tags) resolved.pens = { tags: resolved.tags, series: resolved.series, root: root_tag };
    if (Array.isArray(resolved.series)) resolved.series = resolved.series.map(item =>
      item.tag.startsWith('$.') ? { ...item, tag: root_tag + item.tag.slice(1) } : item);
    return <React.Fragment key={control.id}>{config.components[controlTypes[control.kind]].render(resolved)}</React.Fragment>;
  })}</div></article>;
}
