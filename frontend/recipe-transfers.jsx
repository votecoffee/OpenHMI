import React, { useEffect, useState } from 'react';
import { api, json } from './api.mjs';

export function RecipeTransferPanel({ source, session, reason, dirty, busy, setBusy, loadingAllowed, setMessage }) {
  const [data, setData] = useState(null);
  const [profile, setProfile] = useState('');
  const [before, setBefore] = useState(null);
  const [error, setError] = useState('');
  const identity = session.user?.name;
  useEffect(() => {
    if (!identity) { setData(null); return; }
    let stopped = false, timer;
    async function refresh() {
      try { const result = await api(`/api/recipe-transfers?limit=25${before ? `&before_id=${before}` : ''}`); if (!stopped) { setData(result); setError(''); } }
      catch (problem) { if (!stopped) setError(problem.message); }
      if (!stopped) timer = setTimeout(refresh, 1000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [identity, before]);
  if (!data?.profiles.length) return error ? <p role="alert">PLC transfer status unavailable: {error}</p> : null;
  const target = profile || data.profiles[0].id;
  const unresolved = data.unresolved_profiles.includes(target);
  const allowed = identity && session.user.roles.some(role => ['operator', 'engineer', 'administrator'].includes(role));
  const verified = data.items.find(item => item.profile_id === target && item.transaction.state === 'completed');
  async function dispatch() {
    if (!source || !reason.trim()) { setMessage('Choose a recipe revision and enter a transfer reason.'); return; }
    setBusy(true);
    try {
      const result = await api(`/api/recipe-transfers/${encodeURIComponent(target)}/dispatch`, json('POST', { revision_id: source.id, expected_revision_version: source.version, reason }));
      setMessage(`PLC transfer requested. Transaction ${result.transaction.id}; completion requires PLC acknowledgement and a verified running copy.${result.audit_status === 'pending' ? ' Activity journal finalization is pending.' : ''}`);
      setBefore(null);
      setData(await api('/api/recipe-transfers?limit=25'));
    } catch (problem) { setMessage(problem.message); }
    finally { setBusy(false); }
  }
  return <section aria-label="PLC recipe transfers" className="recipe-transfer-panel"><h2>PLC recipe transfer</h2>
    <p>The PLC decides whether this recipe can run. Library edits and approval changes do not change its running copy.</p>
    <label>PLC transfer target<select aria-label="PLC transfer target" value={target} onChange={event => { setProfile(event.target.value); setBefore(null); }}>{data.profiles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <button disabled={!source || dirty || busy || !allowed || !loadingAllowed || unresolved || !!error} onClick={dispatch}>Transfer revision to PLC</button>
    {unresolved && <p role="status">This target has an unresolved transfer. Verify its outcome before another request.</p>}
    {error && <p role="alert">PLC transfer status unavailable: {error}. Retained records may be outdated.</p>}
    {verified && <div className="loaded-recipe"><div>{verified.snapshot.content.image_id && <img className="recipe-image" src={`/api/recipe-images/${verified.snapshot.content.image_id}`} alt={verified.snapshot.content.title} />}</div><div><strong>Verified transfer record: {verified.snapshot.content.title}</strong><p>{verified.snapshot.code} · revision {verified.snapshot.number} · {verified.snapshot.production_approved ? 'Production approved' : 'Test / not production approved'}</p><p>Verified at {verified.transaction.updated_at}. This is historical evidence; the PLC may change its running copy independently.</p></div></div>}
    <table className="recipe-history"><thead><tr><th>Recipe / transfer</th><th>Production status</th><th>PLC outcome</th><th>Details</th></tr></thead><tbody>{data.items.filter(item => item.profile_id === target).map(item => <tr key={item.id}>
      <td>{item.snapshot.content.title} · {item.snapshot.code} r{item.snapshot.number}<br />Transfer #{item.id} · sequence {item.transaction.sequence}</td>
      <td>{item.snapshot.production_approved ? 'Production approved' : 'Test / not production approved'}<br />{item.snapshot.approved_by && `Approved by ${item.snapshot.approved_by}`}</td>
      <td>{item.transaction.state}{item.transaction.result_code !== null ? ` · result ${item.transaction.result_code}` : ''}</td>
      <td><details><summary>Transfer details</summary><p>Requested by {item.snapshot.transferred_by}: {item.snapshot.transfer_reason}</p><p>{item.transaction.error}</p>{item.transaction.events.map((event, i) => <p key={i}>{event.state}: {event.detail}</p>)}<p>Content hash: {item.snapshot.content_hash}</p><p>Transfer hash: {item.transfer_hash}</p><a href={`/activity?search=${encodeURIComponent(item.transaction.operation_id)}`}>Operator activity</a></details></td>
    </tr>)}</tbody></table>
    <button onClick={() => setBefore(null)}>Newest transfers</button> <button disabled={!data.has_more} onClick={() => setBefore(data.next_before_id)}>Older transfers</button>
  </section>;
}
