import React, { createContext, useContext, useState } from 'react';
import { api, json } from './api.mjs';
import { controlTypes } from './model.mjs';
import { useLocalization, LanguageSelector, alarmMessage } from './localization.jsx';
import { LoadedRecipe } from './recipes.jsx';

export const Live = createContext({ values: {}, connected: false });
export const ScreenControls = createContext([]);

function useValue(tag, type) {
  const live = useContext(Live);
  const value = live.values[tag];
  const valid = live.connected && typeof value === type && (type !== 'number' || Number.isFinite(value));
  return { value, valid, problem: live.connected ? 'BAD DATA' : 'COMM LOSS' };
}

function Quality({ text }) {
  const { ui } = useLocalization();
  const key = { 'BAD DATA': 'badData', 'COMM LOSS': 'commLoss', 'BAD RANGE': 'badRange' }[text];
  return <span className="hmi-quality"><span aria-hidden="true">×</span> {key ? ui(key) : text}</span>;
}

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
    {valid ? <strong className="hmi-value">{formatted} <small>{text(`control.${id}.unit`, unit)}</small></strong> : <Quality text={problem} />}
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
    </strong> : <Quality text={problem} />}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function AnalogRange({ id, label, tag, unit, decimals, minimum, maximum, normal_low, normal_high, puck }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, ui, language } = useLocalization();
  label = text(`control.${id}.label`, label);
  unit = text(`control.${id}.unit`, unit);
  let formatted;
  try { formatted = valid ? new Intl.NumberFormat(language.code, { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: false }).format(value) : ''; }
  catch { formatted = valid ? value.toFixed(decimals) : ''; }
  const configured = [minimum, maximum, normal_low, normal_high].every(Number.isFinite)
    && minimum <= normal_low && normal_low < normal_high && normal_high <= maximum;
  const position = number => Math.max(0, Math.min(100, (number - minimum) / (maximum - minimum) * 100));
  const outside = valid && (value < minimum || value > maximum);
  return <article className="hmi-control hmi-analog" data-control="analog">
    <div className="analog-heading"><span className="hmi-label">{label}</span>
      {valid ? <strong className="hmi-value">{formatted} <small>{unit}</small></strong> : <Quality text={problem} />}</div>
    {!configured ? <Quality text="BAD RANGE" /> : <>
      <div className={`analog-track ${!valid ? 'invalid' : ''}`} role="img"
        aria-label={valid ? `${label}: ${value} ${unit}, scale ${minimum} to ${maximum}, normal ${normal_low} to ${normal_high}${outside ? ', out of scale' : ''}` : `${label}: ${problem}`}>
        <span className="normal-band" style={{ left: `${position(normal_low)}%`, width: `${position(normal_high) - position(normal_low)}%` }} />
        {valid && <span className="analog-pointer" style={{ left: `${position(value)}%` }} aria-hidden="true">▼</span>}
      </div>
      <div className="analog-scale"><span>{minimum}</span><span>{ui('normal')} {normal_low}–{normal_high} {unit}</span><span>{maximum}</span></div>
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
    {!valid ? <Quality text={problem} /> : value ? <strong className="alarm-state"><PrioritySymbol priority={priority} />P{priority} {ui('active')}</strong>
      : <span className="alarm-inactive">{ui('inactive')}</span>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function ActionButton({ id, label, action, puck }) {
  const live = useContext(Live);
  const { text, ui } = useLocalization();
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [failed, setFailed] = useState(false);
  async function invoke() {
    setBusy(true);
    setFailed(false);
    try {
      await api(`/api/actions/${encodeURIComponent(action)}`, json('POST', {}));
      setFeedback(ui('completed'));
    } catch (error) { setFeedback(error.message); setFailed(true); }
    finally { setBusy(false); }
  }
  return <article className="hmi-control hmi-command" data-control="button">
    <button className="hmi-action" disabled={puck?.isEditing || !live.connected || busy} onClick={invoke}>
      {busy ? ui('working') : text(`control.${id}.label`, label)}
    </button><span className={failed ? 'hmi-quality' : 'command-feedback'}>
      {busy ? ui('pending') : puck?.isEditing ? ui('configureAction') : feedback || (!live.connected ? ui('commLoss') : '')}
    </span>
  </article>;
}

function SelectedRecipe({ id, label }) {
  const { text } = useLocalization();
  return <article className="hmi-control hmi-recipe" data-control="recipe"><span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    <LoadedRecipe compact /></article>;
}

function ScreenFrame({ children, title, columns, puck }) {
  const live = useContext(Live);
  const { text, ui, language } = useLocalization();
  const monitor = live.alarms;
  const active = [...(monitor?.outstanding || [])].sort((a, b) => a.priority - b.priority);
  const unknown = !live.alarmConnected || monitor?.error;
  const badQuality = Object.values(monitor?.states || {}).some(state => state.quality === 'bad');
  return <section className="hmi-screen">
    <header className="station-header">
      <div className="station-identity"><strong>OpenHMI</strong><span>{ui('localStation')}</span></div>
      <div className="station-title"><div className={`screen-alarm-banner ${!unknown && active.length ? 'has-alarm' : ''}`} aria-label="Screen alarm status">
        {unknown ? <Quality text={ui('alarmUnavailable')} /> : active.length ? <><PrioritySymbol priority={active[0].priority} />
          <strong>P{active[0].priority} {alarmMessage(active[0], language)} · {ui('activeAlarms', { active: monitor.active_count, unack: monitor.unacknowledged_count })}</strong>
          {badQuality && <Quality text={ui('badData')} />}</> : badQuality ? <Quality text={ui('badData')} />
          : Object.keys(monitor?.states || {}).length ? ui('noActiveAlarms') : ui('noAlarms')}
      </div><h1>{text('screen.title', title)}</h1></div>
      <div className="station-mode"><LanguageSelector /><strong>{ui('simulation')}</strong><span>{live.connected ? ui('dataConnected') : ui('commLoss')}</span></div>
    </header>
    <div className="station-workspace"><div className="hmi-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>{children}</div>
      <aside className="station-sidebar" aria-label="State legend"><strong>{ui('state')}</strong><span><i className="binary-symbol legend-on" /> {ui('on')}</span>
        <span><i className="binary-symbol" /> {ui('off')}</span><span className="sidebar-note">{ui('textShape')}</span></aside></div>
    <footer className="station-footer"><span className="station-location">{ui('overview')}</span>
      <span className="footer-description">{ui('localSimulator')}</span>{puck?.isEditing ? <span>{ui('preview')}</span> : <><a href="/alarms">{ui('alarms')}</a><a href="/">{ui('editScreen')}</a></>}</footer>
  </section>;
}

export function createConfig(catalog) {
  const tagField = type => ({ type: 'select', label: 'Tag', options: catalog.tags
    .filter(tag => tag.type === type).map(tag => ({ label: tag.name, value: tag.name })) });
  const labelField = { type: 'text', label: 'Label' };
  const numericFields = { label: labelField, tag: tagField('number'), unit: { type: 'text', label: 'Units' },
    decimals: { type: 'select', label: 'Decimal places', options: [0, 1, 2, 3, 4].map(value => ({ label: String(value), value })) } };
  const numericDefaults = { label: 'Tank level', tag: 'TankLevel', unit: '%', decimals: 1 };
  return {
    root: {
      fields: { title: { type: 'text', label: 'Screen name' }, columns: { type: 'select', label: 'Columns',
        options: [1, 2, 3].map(value => ({ label: String(value), value })) } },
      defaultProps: { title: 'Station overview', columns: 2 }, render: ScreenFrame,
    },
    categories: { hmi: { title: 'High performance HMI', components: Object.values(controlTypes) } },
    components: {
      SelectedRecipe: { label: 'Selected recipe', fields: { label: labelField }, defaultProps: { label: 'Loaded recipe' }, render: SelectedRecipe },
      NumericDisplay: { label: 'Numeric display', fields: numericFields, defaultProps: numericDefaults, render: NumericDisplay },
      Indicator: {
        label: 'Indicator', fields: { label: labelField, tag: tagField('boolean'), on_text: { type: 'text', label: 'ON text' }, off_text: { type: 'text', label: 'OFF text' } },
        defaultProps: { label: 'Motor', tag: 'MotorRunning', on_text: 'ON', off_text: 'OFF' }, render: Indicator,
      },
      AnalogRange: {
        label: 'Analog range', fields: { ...numericFields, minimum: { type: 'number', label: 'Scale minimum' }, maximum: { type: 'number', label: 'Scale maximum' },
          normal_low: { type: 'number', label: 'Normal low' }, normal_high: { type: 'number', label: 'Normal high' } },
        defaultProps: { ...numericDefaults, label: 'Tank operating range', minimum: 0, maximum: 100, normal_low: 20, normal_high: 80 }, render: AnalogRange,
      },
      AlarmIndicator: {
        label: 'Alarm indicator', fields: { label: labelField, tag: tagField('boolean'), priority: { type: 'select', label: 'Alarm priority',
          options: [1, 2, 3, 4].map(value => ({ label: `Priority ${value}`, value })) } },
        defaultProps: { label: 'Process alarm', tag: 'ProcessAlarm', priority: 2 }, render: AlarmIndicator,
      },
      ActionButton: {
        label: 'Action button', fields: { label: labelField, action: { type: 'select', label: 'Action',
          options: catalog.actions.map(action => ({ label: action.label, value: action.name })) } },
        defaultProps: { label: 'Toggle simulated motor', action: 'toggle_motor' }, render: ActionButton,
      },
    },
  };
}
