import React, { useRef, useState } from 'react';
import { api } from './api.mjs';
import { Popup } from './touch-entry.jsx';

export const projectImagePath = identifier => '/api/canvas-images/' + identifier;
export const projectImageName = asset => asset.name || 'Image ' + asset.id.slice(0, 8);

export function ProjectImagePicker({ label = 'Choose from project', disabled, onSelect }) {
  const [opener, setOpener] = useState(null);
  const [library, setLibrary] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(0);

  async function browse(cursors) {
    const sequence = ++request.current;
    setError('');
    setBusy(true);
    try {
      const before = cursors.at(-1);
      const page = await api('/api/canvas-images' + (before ? '?' + new URLSearchParams({ before }) : ''));
      if (!Array.isArray(page?.items)) throw new Error('Project images could not be listed.');
      if (sequence === request.current) setLibrary({ ...page, cursors });
    } catch (problem) {
      if (sequence === request.current) setError(problem.message);
    } finally {
      if (sequence === request.current) setBusy(false);
    }
  }

  function close() {
    request.current += 1;
    setOpener(null);
    setLibrary(null);
    setError('');
    setBusy(false);
  }

  return <>
    <button type="button" disabled={disabled} aria-haspopup="dialog" onClick={event => {
      setOpener(event.currentTarget);
      browse([null]);
    }}>{label}</button>
    {opener && <Popup title="Project images" opener={opener} close={close}>
      {busy && <p role="status">Loading project images...</p>}
      {error && <p role="alert">{error}</p>}
      {library && <>
        {!library.items.length && <p>No project images</p>}
        <div className="project-image-list">
          {library.items.map(asset => {
            const name = projectImageName(asset);
            return <button key={asset.id} type="button" disabled={disabled || busy} aria-label={'Use ' + name}
              onClick={() => { onSelect(asset); close(); }}>
              <img src={projectImagePath(asset.id)} alt="" loading="lazy" /><span>{name}</span>
            </button>;
          })}
        </div>
        <footer>
          {library.cursors.length > 1 && <button type="button" disabled={busy}
            onClick={() => browse(library.cursors.slice(0, -1))}>Previous images</button>}
          {library.next_before && <button type="button" disabled={busy}
            onClick={() => browse([...library.cursors, library.next_before])}>More images</button>}
        </footer>
      </>}
    </Popup>}
  </>;
}
