import React, { createContext, useContext, useEffect, useState } from 'react';
import { api, json } from './api.mjs';
import { controlTypes } from './model.mjs';
import { useLocalization, LanguageSelector, alarmMessage } from './localization.jsx';
import { LoadedRecipe } from './recipes.jsx';
import { SecurityContext, allowed, SecurityLock, CurrentUser } from './security.jsx';

import { EditControl } from './edit-control.jsx';
import { Trend, TrendFields } from './trend.jsx';
import { TrendRecordingFields } from './trend-recording.jsx';
import { ChartFields, ProcessChart, TankGraphic, chartSeries } from './charts.jsx';

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

function TextDisplay({ id, label, tag, puck }) {
  const { value, valid, problem } = useValue(tag, 'string');
  const { text } = useLocalization();
  return <article className="hmi-control" data-control="text">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {valid ? <strong className="hmi-text-value">{value}</strong> : <Quality text={problem} />}
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
  const graphicLabel = valid ? `${label}: ${value} ${unit}, scale ${minimum} to ${maximum}, normal ${normal_low} to ${normal_high}${outside ? ', out of scale' : ''}` : `${label}: ${problem}`;
  return <article className="hmi-control hmi-analog" data-control={tank ? 'tank' : 'analog'}>
    <div className="analog-heading"><span className="hmi-label">{label}</span>
      {valid ? <strong className="hmi-value">{formatted} <small>{unit}</small></strong> : <Quality text={problem} />}</div>
    {!configured ? <Quality text="BAD RANGE" /> : <>
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
    {!valid ? <Quality text={problem} /> : value ? <strong className="alarm-state"><PrioritySymbol priority={priority} />P{priority} {ui('active')}</strong>
      : <span className="alarm-inactive">{ui('inactive')}</span>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function ActionButton({ id, label, action, mode = 'python', command = '', security_groups = [], puck, enabled_tag = '' }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const definition = mode === 'command' ? live.project?.commands?.find(item => item.id === command) : null;
  const permitted = allowed(session, 'runtime.operate', security_groups) && (mode !== 'command' || !!definition && allowed(session, 'runtime.operate', definition.security_groups));
  const { text, ui } = useLocalization();
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [failed, setFailed] = useState(false);
  const [transaction, setTransaction] = useState(null);
  useEffect(() => {
    if (mode !== 'command' || puck?.isEditing || !permitted) return;
    let stopped = false, timer;
    async function refresh() {
      try { const data = await api(`/api/commands?command_id=${encodeURIComponent(command)}&limit=1`); if (!stopped) setTransaction(data.items[0] || null); }
      catch { if (!stopped) setTransaction(previous => previous ? { ...previous, unavailable: true } : null); }
      if (!stopped) timer = setTimeout(refresh, 1000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [command, mode, permitted, puck?.isEditing]);
  async function invoke() {
    setBusy(true);
    setFailed(false);
    try {
      const result = await api(`/api/controls/${encodeURIComponent(id)}/activate`, json('POST', {}));
      if (result.transaction) setTransaction(result.transaction);
      if (result.mode) window.dispatchEvent(new CustomEvent('openhmi-navigate', { detail: result }));
      setFeedback(result.transaction ? `Request dispatched. Transaction ${result.transaction.id}${result.audit_status === 'pending' ? `; activity finalization pending. Operation ${result.operation_id}` : ''}` : result.audit_status === 'pending' ? `Completed; activity finalization pending. Operation ${result.operation_id}` : ui('completed'));
    } catch (error) { setFeedback(error.message); setFailed(true); }
    finally { setBusy(false); }
  }
  return <article className="hmi-control hmi-command security-protected" data-control="button">
    <button className="hmi-action" disabled={puck?.isEditing || !live.connected || busy || !permitted || !!enabled_tag && live.values[enabled_tag] !== true || !!definition?.permit_member && live.values[`${definition.root_tag}.${definition.permit_member}`] !== true || mode === 'command' && !!transaction && ['prepared', 'requested', 'accepted', 'uncertain'].includes(transaction.state)} onClick={invoke}>
      {busy ? ui('working') : text(`control.${id}.label`, label)}
    </button><span className={failed ? 'hmi-quality' : 'command-feedback'}>
      {busy ? ui('pending') : puck?.isEditing ? ui('configureAction') : feedback || (!live.connected ? ui('commLoss') : !permitted ? 'Sign in with an authorized HMI group' : '')}
    </span>
    {!permitted && !puck?.isEditing && <SecurityLock label={label} permission="runtime.operate" groups={security_groups} additionalGroups={definition?.security_groups || []} />}
    {mode === 'command' && transaction && <span className="command-feedback" role="status">PLC command: {transaction.state} · sequence {transaction.sequence}{transaction.result_code !== null ? ` · result ${transaction.result_code}` : ''}{transaction.unavailable ? ' · status unavailable; verify before retrying' : ''}</span>}
  </article>;
}

function NumericInput(props) { return <EditControl {...props} />; }
function TextInput(props) { return <EditControl {...props} text />; }

function SelectedRecipe({ id, label }) {
  const { text } = useLocalization();
  return <article className="hmi-control hmi-recipe" data-control="recipe"><span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    <LoadedRecipe compact /></article>;
}

function ScreenFrame({ children, title, columns, puck, screen_id = 'overview' }) {
  const live = useContext(Live);
  const { text, ui, language } = useLocalization();
  const plcConfigured = live.project?.connections?.some(connection => connection.enabled);
  const monitor = live.alarms;
  const active = [...(monitor?.annunciated_outstanding || monitor?.outstanding || [])].sort((a, b) => a.priority - b.priority);
  const unknown = !live.alarmConnected || monitor?.error;
  const badQuality = Object.values(monitor?.states || {}).some(state => state.quality === 'bad');
  return <section className="hmi-screen">
    <header className="station-header">
      <div className="station-identity"><strong>OpenHMI</strong><span>{ui('localStation')}</span></div>
      <div className="station-title"><div className={`screen-alarm-banner ${!unknown && active.length ? 'has-alarm' : ''}`} aria-label="Screen alarm status">
        {unknown ? <Quality text={ui('alarmUnavailable')} /> : active.length ? <><PrioritySymbol priority={active[0].priority} />
          <strong>P{active[0].priority} {alarmMessage(active[0], language)} · {ui('activeAlarms', { active: monitor.annunciated_active_count ?? monitor.active_count, unack: monitor.annunciated_unacknowledged_count ?? monitor.unacknowledged_count })}</strong>
          {badQuality && <Quality text={ui('badData')} />}</> : badQuality ? <Quality text={ui('badData')} />
          : monitor?.shelved_count ? ui('noUnshelvedAlarms') : Object.keys(monitor?.states || {}).length ? ui('noActiveAlarms') : ui('noAlarms')}
          {!!monitor?.shelved_count && <a className="shelved-summary" href="/alarms?shelving=shelved">{ui('shelvedSummary', { count: monitor.shelved_count })}</a>}
      </div><h1>{text(screen_id === 'overview' ? 'screen.title' : `screen.${screen_id}.title`, title)}</h1></div>
      <div className="station-mode"><LanguageSelector /><strong>{plcConfigured ? 'PLC' : ui('simulation')}</strong><span>{live.connected ? ui('dataConnected') : ui('commLoss')}</span></div>
    </header>
    <div className="station-workspace"><div className="hmi-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>{children}</div>
      <aside className="station-sidebar" aria-label="State legend"><strong>{ui('state')}</strong><span><i className="binary-symbol legend-on" /> {ui('on')}</span>
        <span><i className="binary-symbol" /> {ui('off')}</span><span className="sidebar-note">{ui('textShape')}</span></aside></div>
    <footer className="station-footer"><span className="station-location">{screen_id === 'overview' ? ui('overview') : text(`screen.${screen_id}.title`, title)}</span>
      <span className="footer-description">{ui(plcConfigured ? 'localPlcRuntime' : 'localSimulator')}</span>{puck?.isEditing ? <span>{ui('preview')}</span> : <><a href="/alarms">{ui('alarms')}</a><a href="/">{ui('editScreen')}</a></>}</footer>
  </section>;
}

function Conditional({ children, visible_tag, enabled_tag, color_tag, active_color, puck }) {
  const live = useContext(Live);
  if (!puck?.isEditing && visible_tag && live.values[visible_tag] !== true) return null;
  const disabled = !puck?.isEditing && enabled_tag && live.values[enabled_tag] !== true;
  return <div className="binding-frame" style={color_tag && live.values[color_tag] === true ? { '--hmi-live': active_color } : {}}>
    <fieldset className="binding-contents" disabled={!!disabled}>{children}</fieldset></div>;
}

function LiveTrend(props) {
  const live = useContext(Live);
  return <Trend {...props} live={live} />;
}

function LiveChart(props) {
  const live = useContext(Live);
  return <ProcessChart {...props} live={live} Quality={Quality} />;
}

export function createConfig(catalog) {
  const groupsField = { type: 'custom', render: ({ value = [], onChange }) => <fieldset className="security-group-choice"><legend>Allowed HMI groups (any selected)</legend>
    {catalog.security_groups.map(group => <label key={group}><input type="checkbox" checked={value.includes(group)} onChange={event => onChange(event.target.checked ? [...value, group] : value.filter(item => item !== group))} />{group}</label>)}
    <small>No groups selected: use the user's operation permission.</small></fieldset> };
  const tagField = type => ({ type: 'select', label: 'Tag', options: catalog.tags
    .filter(tag => tag.type === type).map(tag => ({ label: tag.name, value: tag.name })) });
  const limitTag = label => ({ type: 'select', label, options: [{ label: 'Fixed HMI value', value: '' }, ...catalog.tags.filter(tag => tag.type === 'number').map(tag => ({ label: tag.name, value: tag.name }))] });
  const labelField = { type: 'text', label: 'Label' };
  const numericFields = { label: labelField, tag: tagField('number'), unit: { type: 'text', label: 'Units' },
    decimals: { type: 'select', label: 'Decimal places', options: [0, 1, 2, 3, 4].map(value => ({ label: String(value), value })) } };
  const numericDefaults = { label: 'Tank level', tag: 'TankLevel', unit: '%', decimals: 1 };
  const scaleFields = { minimum: { type: 'number', label: 'Scale minimum' }, maximum: { type: 'number', label: 'Scale maximum' } };
  const analogFields = { ...numericFields, ...scaleFields,
    normal_low: { type: 'number', label: 'Normal low' }, normal_high: { type: 'number', label: 'Normal high' } };
  const analogDefaults = { ...numericDefaults, minimum: 0, maximum: 100, normal_low: 20, normal_high: 80 };
  const chartField = radar => ({ type: 'custom', render: ({ value, onChange }) =>
    <ChartFields value={value} onChange={onChange} catalog={catalog} radar={radar} /> });
  const conditionTag = label => ({ type: 'select', label, options: [{ label: 'Always / none', value: '' }, ...catalog.tags.filter(tag => tag.type === 'boolean').map(tag => ({ label: tag.name, value: tag.name }))] });
  const commonFields = { visible_tag: conditionTag('Visible when tag is true'), enabled_tag: conditionTag('Enabled when tag is true'), color_tag: conditionTag('Color when tag is true'), active_color: { type: 'select', label: 'Active value color', options: [['#002878', 'Navy'], ['#333333', 'Dark gray'], ['#fa3232', 'Priority 1 red'], ['#fff546', 'Priority 2 yellow'], ['#ff9600', 'Priority 3 orange'], ['#ff64c8', 'Priority 4 magenta']].map(([value, label]) => ({ value, label })) } };
  const chartTypes = ['TankLevel', 'BarGraph', 'RadarChart'];
  const config = {
    root: {
      fields: { title: { type: 'text', label: 'Screen name' }, columns: { type: 'select', label: 'Columns',
        options: [1, 2, 3].map(value => ({ label: String(value), value })) } },
      defaultProps: { title: 'Station overview', columns: 2 }, render: ScreenFrame,
    },
    categories: {
      hmi: { title: 'High performance HMI', components: Object.values(controlTypes)
        .filter(type => !chartTypes.includes(type) && (type !== 'Faceplate' || catalog.faceplates?.length)) },
      charts: { title: 'Live charts', components: chartTypes },
    },
    components: {
      Trend: { label: 'Trend', fields: {
        label: labelField, seconds: { type: 'number', label: 'Time window (seconds)', min: 10, max: 604800 },
        pens: { type: 'custom', render: ({ value, onChange }) => <TrendFields value={value} onChange={onChange} catalog={catalog} /> },
        recording: { type: 'custom', render: ({ value, onChange }) => <TrendRecordingFields value={value} onChange={onChange} catalog={catalog} /> },
      }, defaultProps: { label: 'Process trend', pens: { tags: ['TankLevel'], series: {} }, seconds: 300 },
      render: props => <LiveTrend {...props} catalog={catalog} /> },
      Faceplate: { label: 'UDT faceplate', fields: { label: labelField, template: { type: 'select', label: 'Definition', options: (catalog.faceplates || []).map(item => ({ label: item.name, value: item.id })) }, root_tag: tagField('struct') },
        defaultProps: { label: 'Equipment', template: catalog.faceplates?.[0]?.id || '', root_tag: catalog.tags.find(tag => tag.type === 'struct')?.name || '' },
        render: props => <FaceplateInstance {...props} config={config} /> },
      NumericInput: { label: 'Numeric input', fields: { ...numericFields, minimum: { type: 'number', label: 'Minimum' }, maximum: { type: 'number', label: 'Maximum' }, minimum_tag: limitTag('Minimum from tag'), maximum_tag: limitTag('Maximum from tag'), security_groups: groupsField },
        defaultProps: { ...numericDefaults, label: 'Tank setpoint', minimum: 0, maximum: 100, security_groups: [] }, render: NumericInput },
      CurrentUser: { label: 'Current login user', fields: { label: labelField }, defaultProps: { label: 'Current user' }, render: CurrentUser },
      TextDisplay: { label: 'Text display', fields: { label: labelField, tag: tagField('string') },
        defaultProps: { label: 'Status text', tag: 'OperatorText' }, render: TextDisplay },
      TextInput: { label: 'Text input', fields: { label: labelField, tag: tagField('string'), min_length: { type: 'number', label: 'Minimum length' }, max_length: { type: 'number', label: 'Maximum length' }, min_length_tag: limitTag('Minimum length from tag'), max_length_tag: limitTag('Maximum length from tag'), security_groups: groupsField }, defaultProps: { label: 'Operator text', tag: 'OperatorText', min_length: 0, max_length: 82, security_groups: [] }, render: TextInput },
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
    component.render = props => <Conditional {...props}>{renderer(props)}</Conditional>;
  }
  if (!catalog.faceplates?.length) delete config.components.Faceplate;
  return config;
}

function FaceplateInstance({ id, label, template, root_tag, puck, config }) {
  const live = useContext(Live);
  const { text } = useLocalization();
  const definition = live.project?.faceplates?.find(item => item.id === template);
  if (!definition) return <article className="hmi-control" data-control="faceplate"><strong>{label}</strong><p>Faceplate definition unavailable</p></article>;
  return <article className="hmi-faceplate" data-control="faceplate"><strong>{text(`control.${id}.label`, label)}</strong><div className="faceplate-grid">{definition.controls.map(control => {
    const resolved = { ...control, id: `${id}__${control.id}`, puck };
    for (const field of ['tag', 'target', 'visible_tag', 'enabled_tag', 'color_tag']) if (resolved[field]?.startsWith('$.')) resolved[field] = root_tag + resolved[field].slice(1);
    if (resolved.tags) resolved.pens = { tags: resolved.tags, series: resolved.series, root: root_tag };
    if (Array.isArray(resolved.series)) resolved.series = resolved.series.map(item =>
      item.tag.startsWith('$.') ? { ...item, tag: root_tag + item.tag.slice(1) } : item);
    return <React.Fragment key={control.id}>{config.components[controlTypes[control.kind]].render(resolved)}</React.Fragment>;
  })}</div></article>;
}
