import React, { useEffect, useState } from 'react';
import { readWorkspaceArtifacts } from './workspace-api.mjs';

const labels = { connection_hold: 'PLC connection hold', python_review: 'Python saved for review',
  recipe_accounts: 'Recipe accounts', sqlite_wal: 'SQLite WAL', sqlite_shm: 'SQLite shared memory', sqlite_journal: 'SQLite journal' };

export function WorkspaceArtifacts() {
  const [page, setPage] = useState(null);
  const [cursors, setCursors] = useState(['']);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function load(history = ['']) {
    setBusy(true);
    try { const next = await readWorkspaceArtifacts({ after: history.at(-1) }); setPage(next); setCursors(history); setError(''); }
    catch (problem) { if ([401, 403].includes(problem.status)) setPage(null); setError(problem.message); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, []);
  return <section className="workspace-artifacts" aria-label="Project file inventory"><h2>Project file inventory</h2>
    <p>Support and SQLite recovery files can explain why a project name is unavailable. Files beside a database may be normal. This view reads metadata only; it does not inspect contents or change files.</p>
    <button disabled={busy} onClick={() => load()}>Refresh file inventory</button>
    {error && <p role="alert">{page ? 'Showing the last confirmed file inventory. ' : 'File inventory unavailable. '}{error}</p>}
    {!page && !error && <p role="status">Reading file inventory...</p>}
    {page && <>
      {page.scan_limited && <p role="alert">The directory scan was limited. This inventory may be incomplete; review the library folder before reusing a name.</p>}
      <p>Entries without a regular database need review. Do not remove files solely because they appear here; preserve uncertain recovery records.</p>
      <table><caption>Known project support and recovery files</caption><thead><tr><th>File</th><th>Purpose</th><th>Database</th><th>Entry</th><th>Bytes</th></tr></thead>
        <tbody>{page.items.map(item => <tr key={item.file}><td>{item.file}</td><td>{labels[item.kind]}</td>
          <td>{item.project_file}<br />{item.project_entry_type === 'missing' ? 'No database present' : item.project_entry_type === 'file' ? 'Database present' : `Database entry: ${item.project_entry_type} — review required`}</td>
          <td>{item.entry_type}</td><td>{item.size_bytes === null ? 'Unavailable' : item.size_bytes.toLocaleString()}</td></tr>)}</tbody></table>
      {!page.items.length && <p>No matching files in this page.</p>}
      <button disabled={busy || !!error || cursors.length < 2} onClick={() => load(cursors.slice(0, -1))}>Previous files</button>
      <button disabled={busy || !!error || page.next_after === null} onClick={() => load([...cursors, page.next_after])}>Next files</button>
    </>}
  </section>;
}
