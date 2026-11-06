import React, { useContext, useState } from 'react';
import { Live, tagValue, Quality } from './live-quality.jsx';
import { SecurityContext, allowed, SecurityLock } from './security.jsx';
import { useLocalization } from './localization.jsx';
import { TouchEntry } from './touch-entry.jsx';
import { api, json } from './api.mjs';

export function EditControl(props) {
  const { id, tag, security_groups = [], puck, enabled_tag = '', text = false } = props;
  const live = useContext(Live), { session } = useContext(SecurityContext) || {}, { text: translate, ui } = useLocalization();
  const label = translate(`control.${id}.label`, props.label);
  const [draft, setDraft] = useState(null), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [touch, setTouch] = useState(null);
  const entry = draft?.value ?? '';
  const revision = live.activeRevision;
  const authorized = allowed(session, 'runtime.write', security_groups);
  const { value, valid, problem } = tagValue(live, tag, text ? 'string' : 'number');
  const enabled = enabled_tag ? tagValue(live, enabled_tag, 'boolean') : null;
  const bindingEnabled = !enabled || enabled.valid && enabled.value === true;
  const fields = text ? [['min_length', 'editMinLength'], ['max_length', 'editMaxLength']]
    : [['minimum', 'editMinimum'], ['maximum', 'editMaximum']];
  const limitBindings = fields.map(([field, labelKey]) => {
    const source = props[field + '_tag'];
    const state = source ? tagValue(live, source, 'number') : { value: props[field], valid: true };
    return { field, labelKey, source, ...state };
  });
  const [low, high] = limitBindings.map(state => state.valid ? state.value : undefined);
  const validRange = [low, high].every(Number.isFinite) && low <= high
    && (!text || [low, high].every(value => Number.isInteger(value) && value >= 0 && value <= 4096));
  const limitProblem = limitBindings.some(state => !state.valid) ? 'editLimitsUnavailable'
    : !validRange ? 'editLimitsInvalid' : null;
  const limits = { low, high, valid: !limitProblem, problem: limitProblem };
  const bindingProblem = (labelKey, problem) => ui('editBindingProblem', { binding: ui(labelKey), quality: ui(problem) });
  const disabled = puck?.isEditing || !valid || !authorized || !limits.valid || !bindingEnabled || busy;
  async function save(value, expectedRevision) {
    if (expectedRevision !== revision) throw new Error(ui('editRevisionChanged'));
    if (!valid || !bindingEnabled) throw new Error(ui('editDataUnavailable'));
    const measured = text ? Array.from(value).length : value;
    if (limitProblem) throw new Error(ui(limitProblem));
    if (!text && !Number.isFinite(value) || measured < low || measured > high) throw new Error(ui('editOutsideLimits'));
    setBusy(true);
    try { const result = await api(`/api/controls/${encodeURIComponent(id)}/value`, json('PUT', { value, expected_revision: expectedRevision })); setDraft(null); setMessage(result.audit_status === 'pending' ? ui('valueWritePending', { id: result.operation_id }) : ui('valueWritten')); }
    finally { setBusy(false); }
  }
  async function submit(event) { event.preventDefault(); try { if (!text && !entry.trim()) throw new Error(ui('enterValue')); await save(text ? entry : Number(entry), draft?.revision ?? revision); } catch (error) { setMessage(error.message); } }
  return <article className="hmi-control hmi-input security-protected" data-control={text ? 'text_input' : 'input'}><span className="hmi-label">{label}</span>
    {valid ? <strong className="hmi-value">{text ? value : `${value.toFixed(props.decimals ?? 1)} ${props.unit || ''}`}</strong> : <Quality problem={problem} tag={tag} />}
    <small>{limits.valid ? ui(text ? 'textLength' : 'numericRange', limits) : ui(limitProblem)}</small>
    {limitBindings.filter(state => !state.valid).map(({ field, source, labelKey, problem }) =>
      <Quality key={field} tag={source} problem={problem} text={bindingProblem(labelKey, problem)} />)}
    {enabled && !enabled.valid && <Quality tag={enabled_tag} problem={enabled.problem}
      text={bindingProblem('editEnableBinding', enabled.problem)} />}
    {enabled?.valid && !bindingEnabled && <small>{ui('editEnableOff', { tag: enabled_tag })}</small>}
    <form onSubmit={submit}><input aria-label={ui('newControlValue', { label })} type={text ? 'text' : 'number'} min={text ? undefined : low} max={text ? undefined : high} step="any" value={entry} onChange={event => {
      const value = event.target.value;
      setDraft(previous => value ? { value, revision: previous?.revision ?? revision } : null);
    }} disabled={disabled} /><button disabled={disabled}>{ui('writeValue')}</button></form>
    <button disabled={disabled} onClick={() => setTouch({ revision, initial: draft?.revision === revision && entry ? entry : String(value) })}>{ui(text ? 'openTextKeyboard' : 'openNumericKeypad', { label })}</button>
    <span className="command-feedback">{message}</span>{!authorized && !puck?.isEditing && <SecurityLock label={label} permission="runtime.write" groups={security_groups} />}
    {touch && <TouchEntry title={ui(text ? 'textEntryTitle' : 'numericEntryTitle', { label })} numeric={!text} initial={touch.initial} limits={limits} close={() => setTouch(null)} accept={value => save(value, touch.revision)} />}
  </article>;
}
