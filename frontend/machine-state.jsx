import React, { useContext, useState } from 'react';
import { api, json } from './api.mjs';
import { Live, Quality, tagValue } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import { SecurityContext, SecurityLock, allowed } from './security.jsx';

const symbols = { circle: '●', square: '■', triangle: '▲', diamond: '◆' };

export function StateFields({ value = [], onChange }) {
  const edit = (index, key, next) => onChange(value.map((row, i) => i === index ? { ...row, [key]: next } : row));
  const next = Array.from({ length: 32 }, (_, code) => code).find(code => !value.some(row => row.value === code));
  return <fieldset className="chart-fields"><legend>Machine state codes</legend>
    {value.map((row, index) => <fieldset key={index}><legend>State {index + 1}</legend>
      <label>Code<input type="number" step="1" value={row.value ?? ''} onChange={event => {
        const code = event.target.valueAsNumber;
        edit(index, 'value', Number.isSafeInteger(code) ? code : null);
      }} /></label>
      <label>State label<input maxLength={100} value={row.label} onChange={event => edit(index, 'label', event.target.value)} /></label>
      <label>Symbol<select value={row.symbol} onChange={event => edit(index, 'symbol', event.target.value)}>
        {Object.keys(symbols).map(symbol => <option key={symbol}>{symbol}</option>)}
      </select></label>
      <label>Symbol color<input type="color" value={row.color} onChange={event => edit(index, 'color', event.target.value)} /></label>
      <button type="button" disabled={value.length <= 2} onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove state</button>
    </fieldset>)}
    <button type="button" disabled={value.length >= 32} onClick={() => onChange([
      ...value, { value: next, label: 'State ' + next, symbol: 'diamond', color: '#555555' },
    ])}>Add state</button>
  </fieldset>;
}

export function PermissiveFields({ value = [], onChange, catalog }) {
  const tags = catalog.tags.filter(tag => tag.type === 'boolean');
  const edit = (index, key, next) => onChange(value.map((row, i) => i === index ? { ...row, [key]: next } : row));
  return <fieldset className="chart-fields"><legend>Permissive checks</legend>
    {value.map((row, index) => <fieldset key={index}><legend>Check {index + 1}</legend>
      <label>Check tag<select value={row.tag} onChange={event => edit(index, 'tag', event.target.value)}>
        {!tags.some(tag => tag.name === row.tag) && <option value={row.tag}>{row.tag}</option>}
        {tags.map(tag => <option key={tag.name}>{tag.name}</option>)}
      </select></label>
      <label>Check label<input maxLength={100} value={row.label} onChange={event => edit(index, 'label', event.target.value)} /></label>
      <label>Ready when<select value={String(row.expected)} onChange={event => edit(index, 'expected', event.target.value === 'true')}>
        <option value="true">Tag is true</option><option value="false">Tag is false</option>
      </select></label>
      <button type="button" disabled={value.length <= 1} onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove check</button>
    </fieldset>)}
    <button type="button" disabled={value.length >= 32 || !tags.length} onClick={() => onChange([
      ...value, { tag: tags[0].name, label: tags[0].name, expected: true },
    ])}>Add check</button>
  </fieldset>;
}

function readState(live, tag) {
  const sample = tagValue(live, tag, 'number');
  return sample.valid && !Number.isSafeInteger(sample.value) ? { ...sample, valid: false, problem: 'badData' } : sample;
}

function StateReadout({ id, tag, sample, states }) {
  const { text, ui } = useLocalization();
  if (!sample.valid) return <Quality problem={sample.problem} tag={tag} />;
  const state = states.find(item => item.value === sample.value);
  if (!state) return <strong>{ui('machineUnknownState', { value: sample.value })}</strong>;
  return <strong className="machine-state-value">
    <span style={{ color: state.color }} aria-hidden="true">{symbols[state.symbol]}</span>
    {text('control.' + id + '.state.' + state.value, state.label)}
  </strong>;
}

export function MultiState({ id, label, tag, states = [] }) {
  const live = useContext(Live);
  const { text } = useLocalization();
  return <article className="hmi-control" data-control="multi_state">
    <span className="hmi-label">{text('control.' + id + '.label', label)}</span>
    <StateReadout id={id} tag={tag} sample={readState(live, tag)} states={states} />
  </article>;
}

export function ModeSelector({ id, label, tag, confirmed_tag, states = [], presentation,
  security_groups = [], enabled_tag, instance_enabled_tag, puck }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const { text, ui } = useLocalization();
  const [selection, setSelection] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const permitted = allowed(session, 'runtime.write', security_groups);
  const requested = readState(live, tag);
  const confirmed = readState(live, confirmed_tag);
  const revision = live.activeRevision;
  const staleSelection = selection !== null && selection.revision !== revision;
  const selected = staleSelection ? '' : selection?.value ?? '';
  const enabled = [enabled_tag, instance_enabled_tag].every(source => {
    if (!source) return true;
    const condition = tagValue(live, source, 'boolean');
    return condition.valid && condition.value === true;
  });
  const disabled = puck?.isEditing || !permitted || !enabled || !requested.valid || !confirmed.valid || revision == null || busy;
  const controlLabel = text('control.' + id + '.label', label);
  const optionLabel = state => text('control.' + id + '.state.' + state.value, state.label);
  function select(value) {
    setMessage('');
    setSelection(value === '' ? null : { value, revision });
  }
  async function submit(event) {
    event.preventDefault();
    if (disabled || staleSelection || selected === '' || !states.some(state => state.value === selected)) return;
    setBusy(true);
    setMessage('');
    try {
      const result = await api('/api/controls/' + encodeURIComponent(id) + '/value',
        json('PUT', { value: selected, expected_revision: selection.revision }));
      setSelection(null);
      setMessage(result.audit_status === 'pending' ? ui('valueWritePending', { id: result.operation_id }) : ui('valueWritten'));
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }
  return <article className="hmi-control security-protected" data-control="mode_selector">
    <span className="hmi-label">{controlLabel}</span>
    <div>{ui('machineRequestedMode')} <StateReadout id={id} tag={tag} sample={requested} states={states} /></div>
    <div>{ui('machineConfirmedMode')} <StateReadout id={id} tag={confirmed_tag} sample={confirmed} states={states} /></div>
    {requested.valid && confirmed.valid && requested.value !== confirmed.value && <small>{ui('machineWaitingMode')}</small>}
    <form className="machine-mode-options" onSubmit={submit}>
      {presentation === 'segments' ? <div className="machine-mode-segments" role="group" aria-label={controlLabel}>
        {states.map(state => <button key={state.value} type="button" disabled={disabled} aria-pressed={selected === state.value}
          onClick={() => select(state.value)}>{optionLabel(state)}</button>)}
      </div> : <select aria-label={controlLabel} value={selected} disabled={disabled}
        onChange={event => select(event.target.value === '' ? '' : Number(event.target.value))}>
        <option value="">{ui('machineChooseMode')}</option>
        {states.map(state => <option key={state.value} value={state.value}>{optionLabel(state)}</option>)}
      </select>}
      <button disabled={disabled || staleSelection || selected === ''}>{busy ? ui('working') : ui('machineRequestMode')}</button>
    </form>
    <span role="status" className="command-feedback">{staleSelection ? ui('editRevisionChanged') : message}</span>
    {!permitted && !puck?.isEditing && <SecurityLock label={controlLabel} permission="runtime.write" groups={security_groups} />}
  </article>;
}

export function PermissiveList({ id, label, checks = [] }) {
  const live = useContext(Live);
  const { text, ui } = useLocalization();
  const rows = checks.map(check => ({ ...check, ...tagValue(live, check.tag, 'boolean') }));
  const status = rows.some(row => !row.valid) ? 'machineUnavailable'
    : rows.every(row => row.value === row.expected) ? 'machineReady' : 'machineBlocked';
  return <article className="hmi-control" data-control="permissives">
    <span className="hmi-label">{text('control.' + id + '.label', label)}</span>
    <strong>{ui(status)}</strong>
    <ul className="machine-permissives">{rows.map((row, index) => <li key={index}>
      <span>{text('control.' + id + '.check.' + index, row.label)}</span>
      {row.valid ? <strong>{row.value === row.expected ? '✓ ' + ui('machineReady') : '× ' + ui('machineBlocked')}</strong>
        : <Quality problem={row.problem} tag={row.tag} />}
    </li>)}</ul>
  </article>;
}
