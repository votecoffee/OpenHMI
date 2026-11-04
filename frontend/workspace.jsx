import React, { useEffect, useState } from 'react';
import { api, json } from './api.mjs';

export function WorkspacePage() {
  const [state, setState] = useState(null);
  const [message, setMessage] = useState('');
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [importName, setImportName] = useState('');
  const [busy, setBusy] = useState(false);
  async function refresh() { try { setState(await api('/api/workspace')); setMessage(''); } catch (error) { setMessage(`${error.message}. The project library is available when started with openhmi.`); } }
  useEffect(() => { refresh(); }, []);
  async function run(operation) { setBusy(true); try { await operation(); await refresh(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  return <section className="engineering" aria-label="Project library"><h1>Projects</h1><p>Open/create local projects and export/import complete project backups. Opening a project changes this server's active project for all viewers.</p>
    <button disabled={busy} onClick={refresh}>Refresh projects</button><p role="status" aria-label="Project operation">{message}</p>
    {state && <><p>Current project: <strong>{state.current}</strong></p>
      <table><thead><tr><th>Project</th><th /></tr></thead><tbody>{state.projects.map(project => <tr key={project.file}><td>{project.file}{project.current ? ' (open)' : ''}</td><td><button disabled={busy || project.current} onClick={() => run(async () => { await api('/api/workspace/open', json('POST', { file: project.file })); location.href = '/'; })}>Open {project.file}</button></td></tr>)}</tbody></table>
      <fieldset disabled={busy}><legend>Create project</legend><label>New project ID<input value={name} onChange={event => setName(event.target.value)} /></label><label>New project title<input value={title} onChange={event => setTitle(event.target.value)} /></label><button onClick={() => run(async () => { await api('/api/workspace/create', json('POST', { name, title })); setName(''); setTitle(''); })}>Create project</button><p>New projects inherit this project's HMI security configuration. Existing projects are preserved.</p></fieldset>
      <fieldset disabled={busy}><legend>Complete backup</legend><a href="/api/workspace/backup" download>Export complete backup</a><p>Includes database content, recipe images, security/password hashes, alarms, history and the startup Python entry file when configured. Store backups as private project data.</p>
        <label>Imported project ID<input value={importName} onChange={event => setImportName(event.target.value)} /></label><label>OpenHMI backup ZIP<input type="file" accept=".zip" onChange={event => { const file = event.target.files?.[0]; if (file) run(async () => { const result = await api(`/api/workspace/import?name=${encodeURIComponent(importName)}`, { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file }); setMessage(`Imported ${result.file}. PLC connections are held until Apply live.`); }); event.target.value = ''; }} /></label>
        <p>Import creates a new project, verifies checksums and holds PLC connections until Apply live. Imported Python is saved for review and never loaded automatically.</p>
      </fieldset></>}
  </section>;
}
