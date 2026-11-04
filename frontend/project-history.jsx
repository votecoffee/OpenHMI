import React, { useContext, useEffect, useState } from 'react';
import { api, json } from './api.mjs';
import { SecurityContext, allowed } from './security.jsx';
import { readCandidate, recoveryPrefix } from './recovery-cache.mjs';
import './project-history.css';

function valueText(item) {
  if (!item.exists) return '(absent)';
  const text = JSON.stringify(item.value);
  return text.length > 800 ? text.slice(0, 800) + ' … (export the full candidate to inspect)' : text;
}

export function exportCandidate(candidate) {
  const blob = new Blob([JSON.stringify({ format: 'OpenHMI-recovery', version: 1, ...candidate }, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = 'openhmi-local-recovery.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Changes({ items }) {
  return <><table className="project-changes"><thead><tr><th>Project field</th><th>Before</th><th>After</th></tr></thead><tbody>{items.slice(0, 500).map(item => <tr key={item.path}><td>{item.path}</td><td>{valueText(item.before)}</td><td>{valueText(item.after)}</td></tr>)}</tbody></table>{items.length > 500 && <p>Showing 500 of {items.length} changes. Export the revision/candidate for complete content.</p>}{!items.length && <p>No differences.</p>}</>;
}

export function MergeReview({ candidate, onAccepted, onClose }) {
  const [choices, setChoices] = useState({});
  const [preview, setPreview] = useState(null);
  const [reason, setReason] = useState('Recover local editor changes');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [saved, setSaved] = useState('');
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const selection = JSON.stringify(choices);
  useEffect(() => {
    let stopped = false;
    setLoading(true);
    api('/api/project/merge-preview', json('POST', { base: candidate.base, local: candidate.local, choices })).then(result => {
      if (!stopped) { setPreview(result); setMessage(''); }
    }).catch(error => { if (!stopped) { setPreview(null); setMessage(error.message); } }).finally(() => { if (!stopped) setLoading(false); });
    return () => { stopped = true; };
  }, [candidate.base, candidate.local, selection, refreshGeneration]);
  async function preserve() {
    setBusy(true);
    try { const result = await api('/api/project/recoveries', json('POST', { base: candidate.base, local: candidate.local, base_revision: candidate.base_revision, reason: reason || 'Retained local editor candidate' })); setSaved(result.id); setMessage('Recovery copy saved on the server.'); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function merge() {
    setBusy(true);
    try { const result = await api('/api/project/merge', json('POST', { base: candidate.base, local: candidate.local, base_revision: candidate.base_revision, expected_revision: preview.draft_revision, choices, reason })); onAccepted(result); }
    catch (error) { setMessage(`${error.message} Refresh the comparison if the server changed.`); }
    finally { setBusy(false); }
  }
  return <div className="project-review-shade"><section role="dialog" aria-modal="true" aria-label="Recover editor changes" className="project-review">
    <h2>Recover editor changes</h2><p>Your local candidate remains separate from the server draft. Independent changes combine by object ID. Choose local or current for each overlap, then review the resulting changes. List order choices retain other additions.</p>
    <div className="operations-actions"><button onClick={() => exportCandidate(candidate)}>Export local recovery JSON</button><button disabled={busy || !!saved} onClick={preserve}>Save recovery copy on server</button><button disabled={busy} onClick={() => { setChoices({}); setRefreshGeneration(value => value + 1); }}>Refresh comparison</button><button disabled={busy} onClick={onClose}>Keep editing locally</button></div>
    {saved && <p>Server recovery ID: {saved}</p>}{message && <p role="status">{message}</p>}
    {loading ? <p>Comparing against the current server draft…</p> : preview && <>
      <h3>Overlapping changes</h3>{!preview.conflicts.length && <p>No overlapping changes. Review the combined draft below.</p>}
      {preview.conflicts.map((item, index) => <fieldset key={item.path}><legend>{item.path}</legend><p>Base: {valueText(item.base)}</p>
        <label><input type="radio" name={`conflict-${index}`} aria-label={`Use local ${item.path}`} checked={choices[item.path] === 'local'} onChange={() => setChoices({ ...choices, [item.path]: 'local' })} />Local: {valueText(item.local)}</label>
        <label><input type="radio" name={`conflict-${index}`} aria-label={`Use current ${item.path}`} checked={choices[item.path] === 'current'} onChange={() => setChoices({ ...choices, [item.path]: 'current' })} />Current: {valueText(item.current)}</label></fieldset>)}
      <h3>Changes to current server draft {preview.draft_revision}</h3><Changes items={preview.changes} />
      <label>Recovery reason<input aria-label="Recovery reason" value={reason} maxLength={1000} onChange={event => setReason(event.target.value)} /></label>
      <button disabled={busy || loading || !preview.complete || !reason.trim()} onClick={merge}>Save reviewed merged draft</button><p>Saving preserves both candidates and changes the draft only. Apply live remains a separate step in the editor.</p>
    </>}
  </section></div>;
}

export function ProjectHistory() {
  const { session } = useContext(SecurityContext);
  const permitted = allowed(session, 'project.edit');
  const [data, setData] = useState(null), [recovery, setRecovery] = useState(null);
  const [before, setBefore] = useState(null), [recoveryBefore, setRecoveryBefore] = useState(null);
  const [compare, setCompare] = useState(null), [selected, setSelected] = useState(null), [scope, setScope] = useState('screens');
  const [reason, setReason] = useState('Restore reviewed screen revision');
  const [message, setMessage] = useState(''), [candidate, setCandidate] = useState(null), [busy, setBusy] = useState(false);
  const [browserCopies, setBrowserCopies] = useState([]);
  const [comparisonGeneration, setComparisonGeneration] = useState(0);
  async function refresh() {
    const [history, copies] = await Promise.all([api(`/api/project/revisions${before ? `?before_revision=${before}` : ''}`), api(`/api/project/recoveries${recoveryBefore ? `?before_id=${recoveryBefore}` : ''}`)]);
    setData(history); setRecovery(copies);
    setComparisonGeneration(value => value + 1);
    const project = await api('/api/project');
    try { const prefix = recoveryPrefix(project.project_id, session?.user); setBrowserCopies(Object.keys(localStorage).filter(key => key.startsWith(prefix)).map(key => ({ key, candidate: readCandidate(key) })).filter(item => item.candidate)); }
    catch { setMessage('Browser recovery storage is unavailable. Server recovery copies are still listed.'); }
  }
  useEffect(() => { if (permitted) refresh().catch(error => setMessage(error.message)); }, [permitted, before, recoveryBefore, session?.user?.name, session?.user?.provider]);
  useEffect(() => {
    let stopped = false;
    setCompare(null);
    if (selected !== null) api(`/api/project/revisions/${selected}/compare?scope=${scope}`).then(result => { if (!stopped) setCompare(result); }).catch(error => { if (!stopped) setMessage(error.message); });
    return () => { stopped = true; };
  }, [selected, scope, comparisonGeneration]);
  async function stage() {
    setBusy(true);
    try { const result = await api(`/api/project/revisions/${selected}/stage`, json('POST', { expected_revision: compare.draft_revision, scope, reason })); setMessage(`Staged draft ${result.draft_revision}. Previous draft retained as recovery ${result.preserved_recovery_id}. Open the editor to review and Apply live.`); setCompare(null); setSelected(null); await refresh(); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function importRecovery(event) {
    try {
      const file = event.target.files[0];
      if (!file) return;
      if (file.size > 32 * 1024 * 1024) throw new Error('Recovery JSON exceeds 32 MiB');
      const copy = JSON.parse(await file.text());
      const current = await api('/api/project');
      if (copy.format !== 'OpenHMI-recovery' || copy.version !== 1 || !copy.base || !copy.local || !copy.base_revision) throw new Error('Choose an OpenHMI local recovery JSON export');
      if (copy.project_id && copy.project_id !== current.project_id) throw new Error('Recovery belongs to a different project. Open the original project before importing it.');
      setCandidate({ base: copy.base, local: copy.local, base_revision: copy.base_revision });
    } catch (error) { setMessage(error.message); }
    finally { event.target.value = ''; }
  }
  if (!permitted) return <section className="engineering"><h1>Project revisions</h1><p>Sign in with project editing permission to inspect and recover project revisions.</p></section>;
  return <section className="engineering operations" aria-label="Project revisions"><h1>Project revisions and recovery</h1>
    <p>Applied revisions contain project configuration. Restoring stages a draft for review; Apply live records a new revision. PLC memory, recipes, accounts and operation histories are not rolled back.</p>
    <p role="status">{message}</p><div className="operations-actions"><button onClick={() => refresh().catch(error => setMessage(error.message))}>Refresh project history</button><a href="/">Open staged draft in editor</a></div>
    <table className="project-changes"><thead><tr><th>Revision</th><th>Recorded user / time</th><th>Reason / source</th><th /></tr></thead><tbody>{data?.items.map(item => <tr key={item.revision}><td>{item.revision}{item.revision === data.active_revision ? ' · active' : ''}{item.baseline ? ' · baseline' : ''}</td><td>{item.actor} ({item.provider})<br />{item.timestamp}</td><td>{item.reason}{item.source_revision ? ` · derived from revision ${item.source_revision}` : ''}</td><td><button onClick={() => setSelected(item.revision)}>Compare revision {item.revision}</button></td></tr>)}</tbody></table>
    <button onClick={() => setBefore(null)}>Newest revisions</button> <button disabled={!data?.has_more} onClick={() => setBefore(data.next_before_revision)}>Older revisions</button>
    {selected !== null && <section aria-label="Revision comparison"><h2>Compare revision {selected}</h2><label>Restore scope<select aria-label="Restore scope" value={scope} onChange={event => setScope(event.target.value)}><option value="screens">Screens and presentation only</option><option value="project">Full project configuration</option></select></label>
      {compare?.scope === scope && compare?.revision.revision === selected && <><p>Changes to the current draft:</p><Changes items={compare.changes} /><details><summary>Changes from the active project</summary><Changes items={compare.active_changes} /></details>
        <label>Restore reason<input aria-label="Restore reason" maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></label><button disabled={busy || !reason.trim()} onClick={stage}>Stage revision as draft</button><button onClick={() => exportCandidate({ project: compare.revision.project, revision: compare.revision.revision })}>Export revision JSON</button></>}
    </section>}
    <h2>Browser recovery copies</h2>{browserCopies.map((item, index) => <p key={item.key}>{item.candidate.local.title} · base draft {item.candidate.base_revision} <button onClick={() => setCandidate({ ...item.candidate, browser_key: item.key })}>Review browser copy {index + 1}</button></p>)}{!browserCopies.length && <p>No retained browser candidates for this project and account.</p>}
    <h2>Retained recovery copies</h2><label>Import local recovery JSON<input aria-label="Import local recovery JSON" type="file" accept="application/json,.json" onChange={importRecovery} /></label><table className="project-changes"><thead><tr><th>Time / user</th><th>Reason</th><th /></tr></thead><tbody>{recovery?.items.map(item => <tr key={item.id}><td>{item.timestamp}<br />{item.actor} ({item.provider})</td><td>{item.reason}</td><td><button onClick={async () => { try { const copy = await api(`/api/project/recoveries/${item.id}`); setCandidate({ base: copy.base, local: copy.local, base_revision: copy.base_revision }); } catch (error) { setMessage(error.message); } }}>Review recovery {item.id.slice(0, 8)}</button></td></tr>)}</tbody></table>
    <button onClick={() => setRecoveryBefore(null)}>Newest recovery copies</button> <button disabled={!recovery?.has_more} onClick={() => setRecoveryBefore(recovery.next_before_id)}>Older recovery copies</button>
    {candidate && <MergeReview candidate={candidate} onClose={() => setCandidate(null)} onAccepted={result => { if (candidate.browser_key) { try { localStorage.removeItem(candidate.browser_key); } catch {} } setCandidate(null); setMessage(`Recovered merged draft ${result.draft_revision}; open the editor to review and Apply live.`); refresh().catch(error => setMessage(error.message)); }} />}
  </section>;
}
