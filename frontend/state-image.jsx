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

function StatePicture({ identifier, alt }) {
  const { ui } = useLocalization();
  const [failed, setFailed] = useState(false);
  return failed ? <strong className="range-deviation">{ui('stateImageUnavailable')}</strong>
    : <img className="state-image-graphic" src={imagePath(identifier)} alt={alt} draggable={false}
      onError={() => setFailed(true)} />;
}

export function StateImage({ id, label, tag, on_image, off_image, on_text, off_text, show_label, puck }) {
  const { value, valid, problem } = useValue(tag, 'boolean');
  const { text } = useLocalization();
  const title = text(`control.${id}.label`, label);
  const stateText = value ? text(`control.${id}.on_text`, on_text) : text(`control.${id}.off_text`, off_text);
  const image = value ? on_image : off_image;
  const caption = show_label || puck?.isEditing;
  return <article className="hmi-control hmi-state-image" data-control="state_image">
    {caption && <span className="hmi-label">{title}</span>}
    {!valid ? <Quality problem={problem} tag={tag} /> : <>
      {caption && <strong>{stateText}</strong>}
      {image && <StatePicture key={image} identifier={image} alt={caption ? '' : `${title}: ${stateText}`} />}
    </>}
  </article>;
}
