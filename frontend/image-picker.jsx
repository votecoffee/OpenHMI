import React, { useRef, useState } from 'react';
import { api } from './api.mjs';
import { Popup } from './touch-entry.jsx';

export const projectImagePath = identifier => '/api/canvas-images/' + identifier;
export const projectImageName = asset => asset.name || 'Image ' + asset.id.slice(0, 8);

export function ProjectImagePicker({ label = 'Choose from project', disabled, onSelect }) {
  const [opener, setOpener] = useState(null);
  const [library, setLibrary] = useState(null);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(0);

  async function browse(cursors, term = '') {
    const sequence = ++request.current;
    setError('');
    setBusy(true);
    try {
      const before = cursors.at(-1);
      const params = new URLSearchParams();
      if (before) params.set('before', before);
      if (term) params.set('search', term);
      const page = await api('/api/canvas-images' + (params.size ? '?' + params : ''));
      if (!Array.isArray(page?.items) || page.items.some(asset => !/^[a-f0-9]{64}$/.test(asset?.id) || typeof asset.name !== 'string')) {
        throw new Error('Project images could not be listed.');
      }
      if (sequence === request.current) setLibrary({ ...page, cursors, term });
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
    setSearch('');
    setError('');
    setBusy(false);
  }

  return <>
    <button type="button" disabled={disabled} aria-haspopup="dialog" onClick={event => {
      setOpener(event.currentTarget);
      browse([null]);
    }}>{label}</button>
    {opener && <Popup title="Project images" opener={opener} close={close}>
      <form className="project-image-search" onSubmit={event => {
        event.preventDefault();
        if (busy || disabled) return;
        setLibrary(null);
        browse([null], search.trim());
      }}>
        <label>Search project images<input type="search" value={search} maxLength={100}
          onChange={event => setSearch(event.target.value)} /></label>
        <button type="submit" disabled={busy || disabled}>Search</button>
        {(search || library?.term) && <button type="button" disabled={busy || disabled} onClick={() => {
          setSearch('');
          setLibrary(null);
          browse([null]);
        }}>Clear search</button>}
      </form>
      {busy && <p role="status">Loading project images...</p>}
      {error && <p role="alert">{error}</p>}
      {library && <>
        {!library.items.length && <p>{library.term ? 'No matching project images' : 'No project images'}</p>}
        <div className="project-image-list">
          {library.items.map(asset => {
            const name = projectImageName(asset);
            const shortId = asset.id.slice(0, 8);
            return <button key={asset.id} type="button" disabled={disabled || busy}
              aria-label={'Use ' + name + (asset.name ? ' (' + shortId + ')' : '')}
              onClick={() => { onSelect(asset); close(); }}>
              <img src={projectImagePath(asset.id)} alt="" loading="lazy" /><span>{name}</span>
              {asset.name && <small>{shortId}</small>}
            </button>;
          })}
        </div>
        <footer>
          {library.cursors.length > 1 && <button type="button" disabled={busy}
            onClick={() => browse(library.cursors.slice(0, -1), library.term)}>Previous images</button>}
          {library.next_before && <button type="button" disabled={busy}
            onClick={() => browse([...library.cursors, library.next_before], library.term)}>More images</button>}
        </footer>
      </>}
    </Popup>}
  </>;
}
