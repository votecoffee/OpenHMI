import React, { useContext, useRef, useState } from 'react';
import { Live, tagValue, Quality } from './live-quality.jsx';
import { SecurityContext, allowed, SecurityLock } from './security.jsx';
import { useLocalization } from './localization.jsx';
import { TouchEntry } from './touch-entry.jsx';
import { api, json } from './api.mjs';

export const MAX_UTC_EPOCH = 253402300799;
const validUtcEpoch = epoch => Number.isSafeInteger(epoch) && epoch >= 0 && epoch <= MAX_UTC_EPOCH;
const utcFieldValue = epoch => validUtcEpoch(epoch) ? new Date(epoch * 1000).toISOString().slice(0, 19) : '';
export function formatUtcEpoch(epoch) {
  const field = utcFieldValue(epoch);
  return field ? field.replace('T', ' ') + ' UTC' : '';
}

function readUtcField(value) {
  if (!value) return null;
  const epoch = Date.parse(value + 'Z') / 1000;
  return validUtcEpoch(epoch) ? epoch : null;
}

export function DateTimeLimit({ label, value, onChange }) {
  return <label>{label}<input type="datetime-local" step="1"
    min={utcFieldValue(0)} max={utcFieldValue(MAX_UTC_EPOCH)} value={utcFieldValue(value)}
    onChange={event => onChange(readUtcField(event.target.value))} /></label>;
}

export function EditControl(props) {
  const { id, tag, security_groups = [], puck, enabled_tag = '', instance_enabled_tag = '', text = false, multiline = false, barcode = false, dateTime = false, slider = false, sliderInteger = false } = props;
  const live = useContext(Live), { session } = useContext(SecurityContext) || {}, { text: translate, ui } = useLocalization();
  const label = translate(`control.${id}.label`, props.label);
  const [draft, setDraft] = useState(null), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [touch, setTouch] = useState(null);
  const barcodeField = useRef(null);
  const entry = draft?.value ?? '';
  const revision = live.activeRevision;
  const authorized = allowed(session, 'runtime.write', security_groups);
  const { value, valid, problem } = tagValue(live, tag, text ? 'string' : 'number');
  const enabled = enabled_tag ? tagValue(live, enabled_tag, 'boolean') : null;
  const bindingEnabled = !enabled || enabled.valid && enabled.value === true;
  const instanceEnabled = instance_enabled_tag ? tagValue(live, instance_enabled_tag, 'boolean') : null;
  const fields = text ? [['min_length', 'editMinLength'], ['max_length', 'editMaxLength']]
    : [['minimum', 'editMinimum'], ['maximum', 'editMaximum']];
  const limitBindings = fields.map(([field, labelKey]) => {
    const source = props[field + '_tag'];
    const state = source ? tagValue(live, source, 'number') : { value: props[field], valid: true };
    return { field, labelKey, source, ...state };
  });
  const [low, high] = limitBindings.map(state => state.valid ? state.value : undefined);
  const validRange = [low, high].every(Number.isFinite) && low <= high
    && (!text || [low, high].every(value => Number.isInteger(value) && value >= 0 && value <= 4096))
    && (!dateTime || [low, high].every(validUtcEpoch));
  const sliderLow = sliderInteger ? Math.ceil(low) : low;
  const sliderHigh = sliderInteger ? Math.floor(high) : high;
  const sliderRange = 0 < sliderHigh - sliderLow && Number.isFinite(sliderHigh - sliderLow);
  const sliderDraft = draft?.revision === revision ? draft?.value : undefined;
  const sliderDraftValid = sliderDraft !== undefined && Number(sliderDraft) >= sliderLow && Number(sliderDraft) <= sliderHigh;
  const limitProblem = limitBindings.some(state => !state.valid) ? 'editLimitsUnavailable'
    : !validRange || slider && !sliderRange ? 'editLimitsInvalid' : null;
  const limits = { low, high, valid: !limitProblem, problem: limitProblem };
  const bindingProblem = (labelKey, problem) => ui('editBindingProblem', { binding: ui(labelKey), quality: ui(problem) });
  const namedProblem = (labelKey, tag, problem) => ui('editNamedBindingProblem', {
    binding: ui(labelKey), tag, quality: ui(problem),
  });

  function writeBlock(expectedRevision) {
    if ((slider || barcode || dateTime) && revision == null || expectedRevision !== revision) return ui('editRevisionChanged');
    if (!authorized) return ui('editNotAuthorized');
    if (!valid) return namedProblem('editValueBinding', tag, problem);
    for (const [state, source, labelKey] of [
      [instanceEnabled, instance_enabled_tag, 'editInstanceEnableBinding'],
      [enabled, enabled_tag, 'editEnableBinding'],
    ]) {
      if (state && !state.valid) return namedProblem(labelKey, source, state.problem);
      if (state?.value === false) return ui('editEnableOff', { tag: source });
    }
    const badLimit = limitBindings.find(state => !state.valid);
    if (badLimit) return namedProblem(badLimit.labelKey, badLimit.source, badLimit.problem);
    return limitProblem ? ui(limitProblem) : '';
  }

  const writeUnavailable = puck?.isEditing || !!writeBlock(revision);
  const disabled = writeUnavailable || busy;
  async function save(value, expectedRevision) {
    const blockedReason = writeBlock(expectedRevision);
    if (blockedReason) throw new Error(blockedReason);
    if (dateTime && !validUtcEpoch(value)) throw new Error(ui('dateTimeInvalid'));
    if (barcode && (!value || /[\r\n]/.test(value))) throw new Error(ui('barcodeSingleLine'));
    const measured = text ? Array.from(value).length : value;
    if (!text && !Number.isFinite(value) || measured < low || measured > high) throw new Error(ui('editOutsideLimits'));
    setBusy(true);
    try { const result = await api(`/api/controls/${encodeURIComponent(id)}/value`, json('PUT', { value, expected_revision: expectedRevision })); setDraft(null); setMessage(result.audit_status === 'pending' ? ui('valueWritePending', { id: result.operation_id }) : ui('valueWritten')); }
    finally { setBusy(false); }
  }
  async function submit(event) {
    event.preventDefault();
    if ((barcode || dateTime) && (disabled || !entry)) return;
    try {
      if (!text && !entry.trim()) throw new Error(ui('enterValue'));
      await save(text ? entry : Number(entry), draft?.revision ?? revision);
    } catch (error) { setMessage(error.message); }
  }
  function clearBarcode() {
    setDraft(null);
    setMessage('');
    barcodeField.current?.focus();
  }
  return <article className="hmi-control hmi-input security-protected" data-control={slider ? 'slider' : dateTime ? 'date_time' : barcode ? 'barcode_input' : multiline ? 'text_area' : text ? 'text_input' : 'input'}><span className="hmi-label">{label}</span>
    {!valid ? <Quality problem={problem} tag={tag} /> : dateTime && !validUtcEpoch(value)
      ? <strong className="range-deviation">{ui('dateTimeInvalid')}</strong>
      : <strong className="hmi-value">{dateTime ? formatUtcEpoch(value) : text ? value : `${value.toFixed(props.decimals ?? 1)} ${props.unit || ''}`}</strong>}
    <small>{!limits.valid ? ui(limitProblem) : dateTime
      ? ui('dateTimeRange', { low: utcFieldValue(low).replace('T', ' '), high: utcFieldValue(high).replace('T', ' ') })
      : ui(text ? 'textLength' : 'numericRange', limits)}</small>
    {limitBindings.filter(state => !state.valid).map(({ field, source, labelKey, problem }) =>
      <Quality key={field} tag={source} problem={problem} text={bindingProblem(labelKey, problem)} />)}
    {enabled && !enabled.valid && <Quality tag={enabled_tag} problem={enabled.problem}
      text={bindingProblem('editEnableBinding', enabled.problem)} />}
    {enabled?.valid && !bindingEnabled && <small>{ui('editEnableOff', { tag: enabled_tag })}</small>}
    {dateTime ? <form className="hmi-date-time" onSubmit={submit}>
      <input aria-label={ui('dateTimeEntry', { label })} type="datetime-local" step="1"
        min={limits.valid ? utcFieldValue(low) : undefined} max={limits.valid ? utcFieldValue(high) : undefined}
        value={entry ? utcFieldValue(Number(entry)) : ''} disabled={disabled}
        onChange={event => {
          const epoch = readUtcField(event.target.value);
          setDraft(previous => epoch === null ? null : { value: String(epoch), revision: previous?.revision ?? revision });
        }} />
      <button disabled={disabled || !entry}>{ui('writeValue')}</button>
    </form> : barcode ? <form className="hmi-barcode" onSubmit={submit}>
      <input ref={barcodeField} type="text" aria-label={ui('barcodeEntry', { label })}
        placeholder={ui('barcodeFocus')} autoComplete="off" autoCapitalize="none" spellCheck={false}
        value={entry} disabled={writeUnavailable} readOnly={busy}
        onChange={event => {
          const code = event.target.value;
          setDraft(previous => code ? { value: code, revision: previous?.revision ?? revision } : null);
          setMessage('');
        }}
        onPaste={event => {
          if (/[\r\n]/.test(event.clipboardData.getData('text'))) {
            event.preventDefault();
            setDraft(null);
            setMessage(ui('barcodeSingleLine'));
          }
        }}
        onKeyDown={event => {
          if (event.key === 'Enter' && event.repeat) event.preventDefault();
        }} />
      <button disabled={disabled || !entry}>{ui('barcodeSubmit')}</button>
      <button type="button" disabled={disabled || !entry} onClick={clearBarcode}>{ui('barcodeClear')}</button>
    </form> : slider ? <form className="hmi-slider" onSubmit={submit}>
      {sliderRange && <input type="range" aria-label={ui('newControlValue', { label })}
        min={sliderLow} max={sliderHigh} step={sliderInteger ? 1 : 10 ** -(props.decimals ?? 1)}
        value={sliderDraftValid ? sliderDraft : valid ? value : sliderLow} disabled={disabled}
        onChange={event => setDraft({ value: event.target.value, revision })} />}
      {sliderDraft !== undefined && <output>{ui('sliderDraft', { value: sliderDraft })}</output>}
      <button disabled={disabled || !sliderDraftValid}>{ui('writeValue')}</button>
    </form> : <form onSubmit={submit}>{React.createElement(multiline ? 'textarea' : 'input', {
      'aria-label': ui('newControlValue', { label }),
      ...(multiline ? { rows: 3 } : { type: text ? 'text' : 'number', min: text ? undefined : low, max: text ? undefined : high, step: 'any' }),
      value: entry, disabled,
      onChange: event => {
        const value = event.target.value;
        setDraft(previous => value ? { value, revision: previous?.revision ?? revision } : null);
      },
    })}<button disabled={disabled}>{ui('writeValue')}</button></form>}
    {!dateTime && <button disabled={disabled} onClick={() => setTouch({ revision, initial: draft?.revision === revision && entry ? entry : barcode ? '' : String(value) })}>{ui(text ? 'openTextKeyboard' : 'openNumericKeypad', { label })}</button>}
    <span className="command-feedback" role={barcode || dateTime ? 'status' : undefined}>{barcode && busy ? ui('working') : message}</span>{!authorized && !puck?.isEditing && <SecurityLock label={label} permission="runtime.write" groups={security_groups} />}
    {touch && <TouchEntry title={ui(text ? 'textEntryTitle' : 'numericEntryTitle', { label })} numeric={!text} multiline={multiline} initial={touch.initial} limits={limits} blockedReason={writeBlock(touch.revision)} close={() => setTouch(null)} accept={value => save(value, touch.revision)} />}
  </article>;
}
