import React, { useContext, useId, useState } from 'react';
import { api, json } from './api.mjs';
import { Live, Quality, tagValue } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import { SecurityContext, SecurityLock, allowed } from './security.jsx';

export function ChoiceFields({ value, onChange }) {
  const numeric = typeof value[0]?.value !== 'string';
  const next = Array.from({ length: 32 }, (_, index) => numeric ? index : String(index))
    .find(candidate => !value.some(option => option.value === candidate));
  const update = (index, fields) => onChange(value.map((option, i) => i === index ? { ...option, ...fields } : option));
  return <fieldset className="chart-fields"><legend>Choices</legend>
    <label>Value type<select value={numeric ? 'integer' : 'string'} onChange={event => {
      const integer = event.target.value === 'integer';
      onChange(value.map((option, index) => ({ ...option, value: integer ? index : String(option.value) })));
    }}><option value="integer">Integer</option><option value="string">Text</option></select></label>
    {value.map((option, index) => <fieldset key={index}><legend>Choice {index + 1}</legend>
      <label>Choice label<input maxLength={100} value={option.label} onChange={event => update(index, { label: event.target.value })} /></label>
      <label>Tag value<input type={numeric ? 'number' : 'text'} step={numeric ? 1 : undefined} maxLength={4096}
        value={option.value ?? ''} onChange={event => update(index, { value: numeric
          ? Number.isSafeInteger(event.target.valueAsNumber) ? event.target.valueAsNumber : null
          : event.target.value })} /></label>
      <button type="button" disabled={value.length <= 2}
        onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove choice</button>
    </fieldset>)}
    <button type="button" disabled={value.length >= 32} onClick={() => onChange([
      ...value, { value: next, label: 'Choice ' + (value.length + 1) },
    ])}>Add choice</button>
  </fieldset>;
}

export function DiscreteInput({ id, label, tag, kind, options = [], security_groups = [],
  enabled_tag, instance_enabled_tag, puck }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const { text, ui } = useLocalization();
  const group = useId();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const boolean = kind === 'checkbox' || kind === 'toggle_switch';
  const type = boolean ? 'boolean' : typeof options[0]?.value;
  const sample = tagValue(live, tag, type);
  const revision = live.activeRevision;
  const authorized = allowed(session, 'runtime.write', security_groups);
  const enabled = [enabled_tag, instance_enabled_tag].every(source => {
    if (!source) return true;
    const condition = tagValue(live, source, 'boolean');
    return condition.valid && condition.value === true;
  });
  const disabled = puck?.isEditing || !authorized || !enabled || !sample.valid || revision == null || busy;
  const title = text(`control.${id}.label`, label);
  const selected = sample.valid ? options.findIndex(option => option.value === sample.value) : -1;
  const optionLabel = (option, index) => text(`control.${id}.choice.${index}`, option.label);

  async function write(value) {
    if (disabled || value === sample.value) return;
    setBusy(true);
    setMessage('');
    try {
      const result = await api('/api/controls/' + encodeURIComponent(id) + '/value',
        json('PUT', { value, expected_revision: revision }));
      setMessage(result.audit_status === 'pending' ? ui('valueWritePending', { id: result.operation_id }) : ui('valueWritten'));
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  return <article className="hmi-control hmi-discrete security-protected" data-control={kind}>
    <span className="hmi-label">{title}</span>
    {!sample.valid && <Quality problem={sample.problem} tag={tag} />}
    {sample.valid && !boolean && selected === -1 && <small>{ui('inputValueOutsideChoices', { value: sample.value })}</small>}
    {(sample.valid || puck?.isEditing) && (boolean ? <label className="hmi-discrete-option">
      <input aria-label={title} type="checkbox" role={kind === 'toggle_switch' ? 'switch' : undefined}
        checked={sample.valid && sample.value === true} disabled={disabled} onChange={event => write(event.target.checked)} />
      <span aria-hidden="true">{sample.value === true ? ui('on') : ui('off')}</span>
    </label> : kind === 'radio_group' ? <fieldset className="hmi-radio-group" aria-label={title} disabled={disabled}>
      {options.map((option, index) => <label className="hmi-discrete-option" key={index}>
        <input type="radio" name={group} checked={selected === index} onChange={() => write(option.value)} />
        {optionLabel(option, index)}
      </label>)}
    </fieldset> : <select aria-label={title} value={selected < 0 ? '' : String(selected)} disabled={disabled}
      onChange={event => { if (event.target.value !== '') write(options[Number(event.target.value)].value); }}>
      <option value="" disabled>{ui('inputChooseValue')}</option>
      {options.map((option, index) => <option key={index} value={index}>{optionLabel(option, index)}</option>)}
    </select>)}
    <span role="status" className="command-feedback">{busy ? ui('working') : message}</span>
    {!authorized && !puck?.isEditing && <SecurityLock label={title} permission="runtime.write" groups={security_groups} />}
  </article>;
}
