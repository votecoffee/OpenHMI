import React, { useContext, useState } from 'react';
import { Live } from './controls.jsx';
import { SecurityContext, allowed, SecurityLock } from './security.jsx';
import { useLocalization } from './localization.jsx';
import { TouchEntry } from './touch-entry.jsx';
import { api, json } from './api.mjs';

export function EditControl(props) {
  const { id, tag, security_groups = [], puck, enabled_tag = '', text = false } = props;
  const live = useContext(Live), { session } = useContext(SecurityContext) || {}, { text: translate, ui } = useLocalization();
  const label = translate(`control.${id}.label`, props.label);
  const [entry, setEntry] = useState(''), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [touch, setTouch] = useState(false);
  const authorized = allowed(session, 'runtime.write', security_groups);
  const value = live.values[tag];
  const fields = text ? ['min_length', 'max_length'] : ['minimum', 'maximum'];
  const [low, high] = fields.map(field => props[field + '_tag'] ? live.values[props[field + '_tag']] : props[field]);
  const limits = { low, high, valid: [low, high].every(value => typeof value === 'number' && Number.isFinite(value)) && low <= high && (!text || [low, high].every(value => Number.isInteger(value) && value >= 0 && value <= 4096)) };
  const valid = live.connected && (text ? typeof value === 'string' : typeof value === 'number' && Number.isFinite(value));
  const disabled = puck?.isEditing || !valid || !authorized || !limits.valid || !!enabled_tag && live.values[enabled_tag] !== true || busy;
  async function save(value) {
    const measured = text ? Array.from(value).length : value;
    if (!limits.valid || !text && !Number.isFinite(value) || measured < low || measured > high) throw new Error(ui('editOutsideLimits'));
    setBusy(true);
    try { const result = await api(`/api/controls/${encodeURIComponent(id)}/value`, json('PUT', { value })); setEntry(''); setMessage(result.audit_status === 'pending' ? ui('valueWritePending', { id: result.operation_id }) : ui('valueWritten')); }
    finally { setBusy(false); }
  }
  async function submit(event) { event.preventDefault(); try { if (!text && !entry.trim()) throw new Error(ui('enterValue')); await save(text ? entry : Number(entry)); } catch (error) { setMessage(error.message); } }
  return <article className="hmi-control hmi-input security-protected" data-control={text ? 'text_input' : 'input'}><span className="hmi-label">{label}</span>
    {valid ? <strong className="hmi-value">{text ? value : `${value.toFixed(props.decimals ?? 1)} ${props.unit || ''}`}</strong> : <span className="hmi-quality">{ui(live.connected ? 'badData' : 'commLoss')}</span>}
    <small>{limits.valid ? ui(text ? 'textLength' : 'numericRange', limits) : ui('editLimitsUnavailable')}</small>
    <form onSubmit={submit}><input aria-label={ui('newControlValue', { label })} type={text ? 'text' : 'number'} min={text ? undefined : low} max={text ? undefined : high} step="any" value={entry} onChange={event => setEntry(event.target.value)} disabled={disabled} /><button disabled={disabled}>{ui('writeValue')}</button></form>
    <button disabled={disabled} onClick={() => setTouch(true)}>{ui(text ? 'openTextKeyboard' : 'openNumericKeypad', { label })}</button>
    <span className="command-feedback">{message}</span>{!authorized && !puck?.isEditing && <SecurityLock label={label} permission="runtime.write" groups={security_groups} />}
    {touch && <TouchEntry title={ui(text ? 'textEntryTitle' : 'numericEntryTitle', { label })} numeric={!text} initial={entry || String(value)} limits={limits} close={() => setTouch(false)} accept={save} />}
  </article>;
}
