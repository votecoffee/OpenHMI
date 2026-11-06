import React, { useState } from 'react';
import { api } from './api.mjs';
import { Quality, useValue } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';

const imagePath = identifier => '/api/canvas-images/' + identifier;

export function ImageField({ label, value, onChange, readOnly }) {
  const [candidate, setCandidate] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function upload(event) {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    setCandidate('');
    setError('');
    setBusy(true);
    try {
      const { id } = await api('/api/canvas-images', { method: 'POST', body: file, signal: AbortSignal.timeout(15000) });
      setCandidate(id);
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  return <fieldset className="state-image-field" disabled={readOnly}>
    <legend>{label}</legend>
    {value && <img src={imagePath(value)} alt="Current image" />}
    <label>Upload {label}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={upload} /></label>
    {busy && <p role="status">Uploading image...</p>}
    {error && <p role="alert">{error}</p>}
    {candidate && <>
      <img src={imagePath(candidate)} alt="Uploaded image preview" />
      <button type="button" onClick={() => { onChange(candidate); setCandidate(''); }}>Use uploaded image</button>
    </>}
    {value && <button type="button" disabled={busy} onClick={() => { onChange(''); setCandidate(''); }}>Clear image</button>}
  </fieldset>;
}

export function ImageStatesFields({ id, value = [], onChange, readOnly }) {
  const next = Array.from({ length: 32 }, (_, code) => code).find(code => !value.some(state => state.value === code));
  const edit = (index, fields) => onChange(value.map((state, i) => i === index ? { ...state, ...fields } : state));
  return <fieldset className="chart-fields" disabled={readOnly}><legend>State images</legend>
    {value.map((state, index) => <fieldset key={index}><legend>State {index + 1}</legend>
      <label>Code<input type="number" step="1" value={state.value ?? ''} onChange={event => {
        const code = event.target.valueAsNumber;
        edit(index, { value: Number.isSafeInteger(code) ? code : null });
      }} /></label>
      <label>State label<input maxLength={100} value={state.label}
        onChange={event => edit(index, { label: event.target.value })} /></label>
      <ImageField key={id + ':' + index + ':' + state.value} label="Image" value={state.image}
        onChange={image => edit(index, { image })} />
      <button type="button" disabled={value.length <= 2}
        onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove state</button>
    </fieldset>)}
    <button type="button" disabled={value.length >= 32} onClick={() => onChange([
      ...value, { value: next, label: 'State ' + next, image: '' },
    ])}>Add state</button>
  </fieldset>;
}

function StatePicture({ identifier, alt }) {
  const { ui } = useLocalization();
  const [failed, setFailed] = useState(false);
  return failed ? <strong className="range-deviation">{ui('stateImageUnavailable')}</strong>
    : <img className="state-image-graphic" src={imagePath(identifier)} alt={alt} draggable={false}
      onError={() => setFailed(true)} />;
}

function ImageReadout({ kind, title, tag, problem, stateText, image, caption, unknown = false }) {
  return <article className="hmi-control hmi-state-image" data-control={kind}>
    {caption && <span className="hmi-label">{title}</span>}
    {problem ? <Quality problem={problem} tag={tag} /> : <>
      {(caption || unknown) && <strong>{stateText}</strong>}
      {image && <StatePicture key={image} identifier={image} alt={caption ? '' : `${title}: ${stateText}`} />}
    </>}
  </article>;
}

export function StateImage({ id, label, tag, on_image, off_image, on_text, off_text, show_label, puck }) {
  const { value, problem } = useValue(tag, 'boolean');
  const { text } = useLocalization();
  return <ImageReadout kind="state_image" title={text(`control.${id}.label`, label)} tag={tag} problem={problem}
    stateText={value ? text(`control.${id}.on_text`, on_text) : text(`control.${id}.off_text`, off_text)}
    image={value ? on_image : off_image} caption={show_label || puck?.isEditing} />;
}

export function MultiStateImage({ id, label, tag, states = [], show_label, puck }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, ui } = useLocalization();
  const state = valid ? states.find(item => item.value === value) : undefined;
  const quality = problem || (Number.isSafeInteger(value) ? null : 'badData');
  return <ImageReadout kind="multi_state_image" title={text(`control.${id}.label`, label)} tag={tag} problem={quality}
    stateText={state ? text(`control.${id}.state.${state.value}`, state.label) : ui('machineUnknownState', { value })}
    image={state?.image} caption={show_label || puck?.isEditing} unknown={!state} />;
}
