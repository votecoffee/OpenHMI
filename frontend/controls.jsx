import React, { createContext, useContext, useEffect, useState } from 'react';
import { api, json } from './api.mjs';
import { controlTypes } from './model.mjs';
import { useLocalization, LanguageSelector, alarmMessage } from './localization.jsx';
import { LoadedRecipe } from './recipes.jsx';
import { SecurityContext, allowed } from './security.jsx';

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

function ActionButton({ id, label, action, security_groups = [], puck, enabled_tag = '' }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const permitted = allowed(session, 'runtime.operate', security_groups);
  const { text, ui } = useLocalization();
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [failed, setFailed] = useState(false);
  async function invoke() {
    setBusy(true);
    setFailed(false);
    try {
      const result = await api(`/api/controls/${encodeURIComponent(id)}/activate`, json('POST', {}));
      if (result.mode) window.dispatchEvent(new CustomEvent('openhmi-navigate', { detail: result }));
      setFeedback(ui('completed'));
    } catch (error) { setFeedback(error.message); setFailed(true); }
    finally { setBusy(false); }
  }
  return <article className="hmi-control hmi-command" data-control="button">
    <button className="hmi-action" disabled={puck?.isEditing || !live.connected || busy || !permitted || !!enabled_tag && live.values[enabled_tag] !== true} onClick={invoke}>
      {busy ? ui('working') : text(`control.${id}.label`, label)}
    </button><span className={failed ? 'hmi-quality' : 'command-feedback'}>
      {busy ? ui('pending') : puck?.isEditing ? ui('configureAction') : feedback || (!live.connected ? ui('commLoss') : !permitted ? 'Sign in with an authorized HMI group' : '')}
    </span>
  </article>;
}

function NumericInput({ id, label, tag, unit, decimals, minimum, maximum, security_groups = [], puck, enabled_tag = '' }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const { text } = useLocalization();
  const { value, valid, problem } = useValue(tag, 'number');
  const [entry, setEntry] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const permitted = allowed(session, 'runtime.write', security_groups) && (!enabled_tag || live.values[enabled_tag] === true);
  async function write(event) {
    event.preventDefault(); setBusy(true);
    try { if (!entry.trim()) throw new Error('Enter a value'); await api(`/api/controls/${encodeURIComponent(id)}/value`, json('PUT', { value: Number(entry) })); setEntry(''); setMessage('Value written'); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <article className="hmi-control hmi-input" data-control="input"><span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {valid ? <strong className="hmi-value">{value.toFixed(decimals)} {unit}</strong> : <Quality text={problem} />}
    <form onSubmit={write}><input aria-label={`${label} new value`} type="number" min={minimum} max={maximum} step="any" value={entry} onChange={event => setEntry(event.target.value)} disabled={puck?.isEditing || !valid || !live.connected || !permitted || busy} />
      <button disabled={puck?.isEditing || !valid || !live.connected || !permitted || busy}>Write value</button></form>
    <span className="command-feedback">{!permitted ? 'Read only — authorized HMI group required' : message}</span><TagReference tag={tag} puck={puck} />
  </article>;
}

function SelectedRecipe({ id, label }) {
  const { text } = useLocalization();
  return <article className="hmi-control hmi-recipe" data-control="recipe"><span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    <LoadedRecipe compact /></article>;
}

function ScreenFrame({ children, title, columns, puck, screen_id = 'overview' }) {
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
      </div><h1>{text(screen_id === 'overview' ? 'screen.title' : `screen.${screen_id}.title`, title)}</h1></div>
      <div className="station-mode"><LanguageSelector /><strong>{live.driver === 'logix' ? 'PLC' : ui('simulation')}</strong><span>{live.connected ? ui('dataConnected') : ui('commLoss')}</span></div>
    </header>
    <div className="station-workspace"><div className="hmi-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>{children}</div>
      <aside className="station-sidebar" aria-label="State legend"><strong>{ui('state')}</strong><span><i className="binary-symbol legend-on" /> {ui('on')}</span>
        <span><i className="binary-symbol" /> {ui('off')}</span><span className="sidebar-note">{ui('textShape')}</span></aside></div>
    <footer className="station-footer"><span className="station-location">{screen_id === 'overview' ? ui('overview') : text(`screen.${screen_id}.title`, title)}</span>
      <span className="footer-description">{ui('localSimulator')}</span>{puck?.isEditing ? <span>{ui('preview')}</span> : <><a href="/alarms">{ui('alarms')}</a><a href="/">{ui('editScreen')}</a></>}</footer>
  </section>;
}

function Conditional({ children, visible_tag, enabled_tag, color_tag, active_color, puck }) {
  const live = useContext(Live);
  if (!puck?.isEditing && visible_tag && live.values[visible_tag] !== true) return null;
  const disabled = !puck?.isEditing && enabled_tag && live.values[enabled_tag] !== true;
  return <div className="binding-frame" style={color_tag && live.values[color_tag] === true ? { '--hmi-live': active_color } : {}}>
    <fieldset className="binding-contents" disabled={!!disabled}>{children}</fieldset></div>;
}

function Trend({ label, tags = ['TankLevel'], seconds = 300, puck }) {
  const [history, setHistory] = useState(null);
  const [error, setError] = useState('');
  const [windowSeconds, setWindowSeconds] = useState(seconds);
  const [endTime, setEndTime] = useState('');
  useEffect(() => setWindowSeconds(seconds), [seconds]);
  useEffect(() => {
    let stopped = false, timer;
    async function tick() { try { const result = await api(`/api/history?tags=${encodeURIComponent(tags.join(','))}&seconds=${windowSeconds}${endTime ? `&end=${Date.parse(endTime) / 1000}` : ''}`); if (!stopped) { setHistory(result); setError(''); } } catch (problem) { if (!stopped) setError(problem.message); } if (!stopped && !endTime) timer = setTimeout(tick, 1000); }
    tick(); return () => { stopped = true; clearTimeout(timer); };
  }, [tags.join(','), windowSeconds, endTime]);
  const good = (history?.samples || []).filter(item => item.quality === 'good' && typeof item.value === 'number');
  const values = good.map(item => item.value), minimum = Math.min(...values, 0), maximum = Math.max(...values, 1);
  const colors = ['#002878', '#555', '#885500', '#225555'];
  return <article className="hmi-control hmi-trend" data-control="trend"><span className="hmi-label">{label}</span>
    {!puck?.isEditing && <div className="trend-tools"><label>Time range<select aria-label={`${label} time range`} value={windowSeconds} onChange={event => setWindowSeconds(Number(event.target.value))}>{[...new Set([seconds, 60, 300, 900, 3600, 86400])].sort((a,b) => a-b).map(value => <option key={value} value={value}>{value < 3600 ? `${value / 60} min` : `${value / 3600} h`}</option>)}</select></label>
      <label>End time<input aria-label={`${label} history end`} type="datetime-local" value={endTime} onChange={event => setEndTime(event.target.value)} /></label><button onClick={() => setEndTime('')}>Live</button></div>}
    {error ? <Quality text="BAD DATA" /> : <><svg role="img" aria-label={`${label} trend`} viewBox="0 0 500 170"><path d="M40 10V140H490" fill="none" stroke="#888" /><text x="2" y="18">{maximum.toFixed(1)}</text><text x="2" y="138">{minimum.toFixed(1)}</text>
      {tags.map((tag, index) => { const segments = [[]]; for (const item of history?.samples.filter(row => row.tag === tag) || []) { if (item.quality !== 'good' || typeof item.value !== 'number') { segments.push([]); continue; } segments.at(-1).push(`${40 + 450 * (item.epoch - history.start) / windowSeconds},${140 - 125 * (item.value - minimum) / (maximum - minimum || 1)}`); } return segments.map((points, i) => <polyline key={`${tag}-${i}`} points={points.join(' ')} fill="none" stroke={colors[index % colors.length]} strokeWidth="1.5" />); })}
      <text x="40" y="162">−{windowSeconds}s</text><text x="455" y="162">{endTime ? 'End' : 'Now'}</text></svg><div>{tags.map((tag, i) => <span key={tag} style={{ color: colors[i % colors.length], marginRight: 12 }}>{tag}</span>)}</div>
      {!good.length && <p>No recorded numeric samples yet. Configure SQL history for these tags.</p>}{history?.truncated && <p>Result limited; shorten the time range.</p>}</>}
    {!puck?.isEditing && <a href={`/api/history.csv?tags=${encodeURIComponent(tags.join(','))}&seconds=${windowSeconds}${endTime ? `&end=${Date.parse(endTime) / 1000}` : ''}`}>Export history CSV</a>}
  </article>;
}

export function createConfig(catalog) {
  const groupsField = { type: 'custom', render: ({ value = [], onChange }) => <fieldset className="security-group-choice"><legend>Allowed HMI groups (any selected)</legend>
    {catalog.security_groups.map(group => <label key={group}><input type="checkbox" checked={value.includes(group)} onChange={event => onChange(event.target.checked ? [...value, group] : value.filter(item => item !== group))} />{group}</label>)}
    <small>No groups selected: use the user's operation permission.</small></fieldset> };
  const tagField = type => ({ type: 'select', label: 'Tag', options: catalog.tags
    .filter(tag => tag.type === type).map(tag => ({ label: tag.name, value: tag.name })) });
  const labelField = { type: 'text', label: 'Label' };
  const numericFields = { label: labelField, tag: tagField('number'), unit: { type: 'text', label: 'Units' },
    decimals: { type: 'select', label: 'Decimal places', options: [0, 1, 2, 3, 4].map(value => ({ label: String(value), value })) } };
  const numericDefaults = { label: 'Tank level', tag: 'TankLevel', unit: '%', decimals: 1 };
  const conditionTag = label => ({ type: 'select', label, options: [{ label: 'Always / none', value: '' }, ...catalog.tags.filter(tag => tag.type === 'boolean').map(tag => ({ label: tag.name, value: tag.name }))] });
  const commonFields = { visible_tag: conditionTag('Visible when tag is true'), enabled_tag: conditionTag('Enabled when tag is true'), color_tag: conditionTag('Color when tag is true'), active_color: { type: 'select', label: 'Active value color', options: [['#002878', 'Navy'], ['#333333', 'Dark gray'], ['#fa3232', 'Priority 1 red'], ['#fff546', 'Priority 2 yellow'], ['#ff9600', 'Priority 3 orange'], ['#ff64c8', 'Priority 4 magenta']].map(([value, label]) => ({ value, label })) } };
  const config = {
    root: {
      fields: { title: { type: 'text', label: 'Screen name' }, columns: { type: 'select', label: 'Columns',
        options: [1, 2, 3].map(value => ({ label: String(value), value })) } },
      defaultProps: { title: 'Station overview', columns: 2 }, render: ScreenFrame,
    },
    categories: { hmi: { title: 'High performance HMI', components: Object.values(controlTypes).filter(type => type !== 'Faceplate' || catalog.faceplates?.length) } },
    components: {
      Trend: { label: 'Trend', fields: { label: labelField, seconds: { type: 'number', label: 'Time window (seconds)' }, tags: { type: 'custom', render: ({ value = [], onChange }) => <fieldset><legend>Trend tags</legend>{catalog.tags.filter(tag => tag.type === 'number').map(tag => <label key={tag.name} style={{ display: 'block' }}><input type="checkbox" checked={value.includes(tag.name)} onChange={event => onChange(event.target.checked ? [...value, tag.name] : value.filter(item => item !== tag.name))} />{tag.name}</label>)}</fieldset> } }, defaultProps: { label: 'Process trend', tags: ['TankLevel'], seconds: 300 }, render: Trend },
      Faceplate: { label: 'UDT faceplate', fields: { label: labelField, template: { type: 'select', label: 'Definition', options: (catalog.faceplates || []).map(item => ({ label: item.name, value: item.id })) }, root_tag: tagField('struct') },
        defaultProps: { label: 'Equipment', template: catalog.faceplates?.[0]?.id || '', root_tag: catalog.tags.find(tag => tag.type === 'struct')?.name || '' },
        render: props => <FaceplateInstance {...props} config={config} /> },
      NumericInput: { label: 'Numeric input', fields: { ...numericFields, minimum: { type: 'number', label: 'Minimum' }, maximum: { type: 'number', label: 'Maximum' }, security_groups: groupsField },
        defaultProps: { ...numericDefaults, label: 'Tank setpoint', minimum: 0, maximum: 100, security_groups: [] }, render: NumericInput },
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
        label: 'Action button', fields: { label: labelField, security_groups: groupsField,
          mode: { type: 'select', label: 'Action type', options: [['python', 'Python action'], ['set', 'Set tag'], ['toggle', 'Toggle Boolean tag'], ['navigate', 'Navigate to screen'], ['popup', 'Open popup'], ['close_popup', 'Close popup']].map(([value, label]) => ({ value, label })) },
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
    if (resolved.tags) resolved.tags = resolved.tags.map(tag => tag.startsWith('$.') ? root_tag + tag.slice(1) : tag);
    return <React.Fragment key={control.id}>{config.components[controlTypes[control.kind]].render(resolved)}</React.Fragment>;
  })}</div></article>;
}
