import React, { useEffect, useRef, useState } from 'react';
import { readWorkspaceLibrary, createWorkspaceProject, openWorkspaceProject, importWorkspaceProject } from './workspace-api.mjs';
import { WorkspaceArtifacts } from './workspace-artifacts.jsx';
import { fetchWorkspaceBackup, saveWorkspaceBackup } from './workspace-backup.mjs';

export function WorkspacePage() {
  const [state, setState] = useState(null);
  const [available, setAvailable] = useState(false);
  const [libraryError, setLibraryError] = useState('');
  const [message, setMessage] = useState('');
  const [operationError, setOperationError] = useState(false);
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [importName, setImportName] = useState('');
  const [backupFile, setBackupFile] = useState(null);
  const fileInput = useRef(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const locked = busy || loading || !available;
  async function refresh(clearMessage = true) {
    setLoading(true);
    if (clearMessage) { setMessage(''); setOperationError(false); }
    try { setState(await readWorkspaceLibrary()); setAvailable(true); setLibraryError(''); }
    catch (error) {
      if ([401, 403].includes(error.status)) setState(null);
      setAvailable(false); setLibraryError(error.message);
    } finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);
  async function run(operation) {
    setBusy(true); setMessage(''); setOperationError(false);
    try { const confirmation = await operation(); await refresh(false); setMessage(confirmation ?? ''); }
    catch (error) {
      if ([401, 403].includes(error.status)) { setState(null); setAvailable(false); }
      else if (error.requiresReview) setAvailable(false);
      setOperationError(true); setMessage(error.message);
    } finally { setBusy(false); }
  }
  return <section className="engineering" aria-label="Project library"><h1>Projects</h1><p>Open/create local projects and export/import complete project backups. Opening a project changes this server's active project for all viewers.</p>
    <button disabled={busy || loading} onClick={() => refresh()}>Refresh projects</button>
    {libraryError && <p role="alert" aria-label="Project library availability">{state ? 'Showing the last confirmed project library. ' : 'Project library unavailable. '}{libraryError}</p>}
    <p role={operationError ? 'alert' : 'status'} aria-label="Project operation">{message}</p>
    {!state && !libraryError && <p role="status">Reading project library...</p>}
    {state && <><p>Current project: <strong>{state.current}</strong></p>
      <table><thead><tr><th>Project</th><th /></tr></thead><tbody>{state.projects.map(project => <tr key={project.file}><td>{project.file}{project.current ? ' (open)' : ''}</td><td><button disabled={locked || project.current} onClick={() => run(async () => { await openWorkspaceProject(project.file); location.href = '/'; })}>Open {project.file}</button></td></tr>)}</tbody></table>
      <fieldset disabled={locked}><legend>Create project</legend><label>New project ID<input value={name} onChange={event => setName(event.target.value)} /></label><label>New project title<input value={title} onChange={event => setTitle(event.target.value)} /></label><button onClick={() => run(async () => { const result = await createWorkspaceProject(name, title); setName(''); setTitle(''); return `Created ${result.file}.`; })}>Create project</button><p>New projects inherit this project's HMI security configuration. Existing projects are preserved.</p></fieldset>
      <fieldset disabled={locked}><legend>Complete backup</legend><button disabled={locked} onClick={() => run(async () => { const backup = await fetchWorkspaceBackup(); saveWorkspaceBackup(backup); return 'Complete backup prepared for download. Verify the saved archive before relying on it.'; })}>Export complete backup</button><p>Includes database content, recipe images, security/password hashes, alarms, history and the startup Python entry file when configured. Store backups as private project data.</p>
        <label>Imported project ID<input value={importName} onChange={event => setImportName(event.target.value)} /></label><label>OpenHMI backup ZIP<input ref={fileInput} type="file" accept=".zip" onChange={event => setBackupFile(event.target.files?.[0] ?? null)} /></label>
        {backupFile && <p>Selected backup: {backupFile.name}</p>}
        <button disabled={locked || !backupFile} onClick={() => run(async () => { const result = await importWorkspaceProject(importName, backupFile); setBackupFile(null); if (fileInput.current) fileInput.current.value = ''; return `Imported ${result.file}. PLC connections are held until Apply live.`; })}>Import complete backup</button>
        <p>Select a backup, then use Import complete backup. Import creates a new project, verifies checksums and holds PLC connections until Apply live. Imported Python is saved for review and never loaded automatically.</p>
      </fieldset><WorkspaceArtifacts /></>}
  </section>;
}
