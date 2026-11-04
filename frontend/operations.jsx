import React, { useContext, useEffect, useState } from 'react';
import { api } from './api.mjs';
import { SecurityContext, allowed } from './security.jsx';

function canInspect(session, permission) {
  return allowed(session, permission) || !!session?.user?.permissions.includes('security.manage');
}

function activityParams(filters, before) {
  const query = new URLSearchParams();
  for (const key of ['actor', 'status', 'search']) if (filters[key]) query.set(key, filters[key]);
  for (const key of ['start', 'end']) if (filters[key]) query.set(key, new Date(filters[key]).toISOString());
  if (before) query.set('before_id', before);
  return query;
}

export function ActivityConsole() {
  const { session } = useContext(SecurityContext);
  const permitted = canInspect(session, 'activity.view');
  const [filters, setFilters] = useState({ actor: '', status: '', search: '', start: '', end: '' });
  const [applied, setApplied] = useState(filters);
  const [before, setBefore] = useState(null);
  const [data, setData] = useState(null);
  const [message, setMessage] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!permitted) { setData(null); return; }
    let stopped = false, timer;
    async function tick() {
      try { const result = await api(`/api/activity?${activityParams(applied, before)}`); if (!stopped) { setData(result); setMessage(''); } }
      catch (error) { if (!stopped) setMessage(error.message); }
      if (!stopped && !before) timer = setTimeout(tick, 5000);
    }
    tick(); return () => { stopped = true; clearTimeout(timer); };
  }, [permitted, applied, before, refresh]);
  function value(key, text) { setFilters(previous => ({ ...previous, [key]: text })); }
  if (!permitted) return <section className="engineering"><h1>Operator activity</h1><p>Sign in with activity viewing permission to inspect the operator journal.</p></section>;
  return <section className="engineering operations" aria-label="Operator activity"><h1>Operator activity</h1>
    <p>Attempts are recorded before dispatch. Confirmed outcomes describe the indicated verification; tag readback or a Python callback return does not mean equipment completed a command.</p>
    <form className="operations-filters" onSubmit={event => { event.preventDefault(); setApplied({ ...filters }); setBefore(null); }}>
      <label>User<input value={filters.actor} onChange={event => value('actor', event.target.value)} /></label>
      <label>Outcome<select value={filters.status} onChange={event => value('status', event.target.value)}><option value="">All outcomes</option>{['pending', 'succeeded', 'denied', 'rejected', 'uncertain', 'interrupted'].map(status => <option key={status}>{status}</option>)}</select></label>
      <label>Control, tag or operation ID<input value={filters.search} onChange={event => value('search', event.target.value)} /></label>
      <label>From<input type="datetime-local" value={filters.start} onChange={event => value('start', event.target.value)} /></label>
      <label>To<input type="datetime-local" value={filters.end} onChange={event => value('end', event.target.value)} /></label>
      <button>Apply activity filters</button>
    </form>
    <div className="operations-actions"><button onClick={() => { setBefore(null); setRefresh(value => value + 1); }}>Newest activity</button><button disabled={!data?.has_more} onClick={() => setBefore(data.next_before_id)}>Older activity</button>
      <a href={`/api/activity.csv?${activityParams(applied)}`}>Export activity CSV</a></div>
    {message && <p role="alert">{message}</p>}
    {data?.pending_finalizations > 0 && <p role="status">{data.pending_finalizations} journal finalizations are pending. Commands are not replayed to repair the journal.</p>}
    <table className="activity-table"><thead><tr><th>Time / operation ID</th><th>User</th><th>Operation / target</th><th>Outcome</th><th>Details</th></tr></thead><tbody>{data?.items.map(item => <tr key={item.operation_id} data-outcome={item.status}>
      <td>{new Date(item.started_at).toLocaleString()}<br /><small>{item.operation_id}</small></td><td>{item.actor}<br /><small>{item.provider} · {item.groups.join(', ')}</small></td>
      <td>{item.operation}<br />{item.context.tag || item.context.target || item.entity}</td><td><strong>{item.status}</strong><br /><small>{item.phase}</small></td>
      <td><details><summary>Operation details</summary><p>Control: {item.entity}</p><p>Last cached before value: {JSON.stringify(item.context.before?.value ?? null)} · {item.context.before?.quality || 'not captured'}</p>
        <p>Before acquisition time: {item.context.before?.timestamp || 'not captured'}</p><p>Requested value: {JSON.stringify(item.context.requested_value ?? item.context.value ?? null)}</p>
        <p>Verification: {item.outcome?.verification || 'not confirmed'}</p>{item.outcome?.count != null && <p>Acknowledged occurrences: {item.outcome.count}</p>}
        <p>Outcome observed: {item.outcome?.observed_at ? new Date(item.outcome.observed_at).toLocaleString() : 'not captured'}</p>
        <p>Finalized / recovered: {item.finished_at ? new Date(item.finished_at).toLocaleString() : 'pending'}</p></details>{item.error && <p className="activity-error">{item.error}</p>}</td>
    </tr>)}</tbody></table>
    {data && !data.items.length && <p>No matching operator activity.</p>}
    <p>Resolved records: {data?.retention_days || 365} days / {data?.max_resolved_rows || 100000} rows. Pending and uncertain outcomes are retained for investigation. CSV export is limited to 20,000 matching records.</p>
  </section>;
}

export function DiagnosticsConsole() {
  const { session } = useContext(SecurityContext);
  const permitted = canInspect(session, 'diagnostics.view');
  const [filter, setFilter] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [message, setMessage] = useState('');
  useEffect(() => {
    if (!permitted) { setData(null); return; }
    let stopped = false, timer;
    async function tick() { try { const result = await api(`/api/diagnostics?search=${encodeURIComponent(search)}&offset=${offset}`); if (!stopped) { setData(result); setMessage(''); } } catch (error) { if (!stopped) setMessage(error.message); } if (!stopped) timer = setTimeout(tick, 2000); }
    tick(); return () => { stopped = true; clearTimeout(timer); };
  }, [permitted, search, offset]);
  if (!permitted) return <section className="engineering"><h1>Runtime diagnostics</h1><p>Sign in with diagnostics viewing permission to inspect runtime status.</p></section>;
  return <section className="engineering operations" aria-label="Runtime diagnostics"><h1>Runtime diagnostics</h1><p>Viewing diagnostics reads cached runtime state. It does not subscribe new tags or issue equipment writes.</p>
    {message && <p role="alert">{message}</p>}{data?.plc_hold && <p role="status">Imported PLC connections are held until reviewed and applied.</p>}
    <h2>Connections and scans</h2><table><thead><tr><th>Connection / route</th><th>State</th><th>Read calls / addresses</th><th>Effective groups</th><th>Error</th></tr></thead><tbody>{data?.connections.map(connection => <tr key={connection.id}><td>{connection.name}<br />{connection.path}</td><td>{connection.state}</td><td>{connection.read_calls} / {connection.tags_read}</td><td>{connection.groups.map(group => <details key={group.rate_ms}><summary>{group.rate_ms} ms · {group.addresses.length} addresses</summary>{group.addresses.join(', ')}</details>)}</td><td>{connection.error || '—'}</td></tr>)}</tbody></table>
    {data && !data.connections.length && <p>No PLC connections are configured.</p>}
    <p>Scan intervals are best effort. Counters are pycomm3 read calls/requested addresses, not wire-packet measurements.</p>
    <h2>Tag quality</h2><form onSubmit={event => { event.preventDefault(); setSearch(filter); setOffset(0); }}><label>Tag filter<input value={filter} onChange={event => setFilter(event.target.value)} /></label><button>Filter diagnostic tags</button></form>
    <div className="operations-actions"><button disabled={!offset} onClick={() => setOffset(0)}>First tags</button><button disabled={data?.next_offset == null} onClick={() => setOffset(data.next_offset)}>More tags</button><a href={`/api/diagnostics.json?search=${encodeURIComponent(search)}`}>Export diagnostics JSON</a></div>
    <p>{data?.total_tags || 0} matching logical tags. Values are omitted from this diagnostic export.</p>
    <table className="diagnostics-tags"><thead><tr><th>Tag / source</th><th>Type</th><th>Quality</th><th>Age (s)</th><th>Acquisition time / error</th></tr></thead><tbody>{data?.tags.map(tag => <tr key={tag.name}><td>{tag.name}<br /><small>{tag.connection || 'Local'} · {tag.address}</small></td><td>{tag.type}</td><td><strong>{tag.quality}</strong></td><td>{tag.age_seconds == null ? '—' : tag.age_seconds.toFixed(2)}</td><td>{tag.timestamp ? new Date(tag.timestamp).toLocaleString() : 'No sample'}<br />{tag.error}</td></tr>)}</tbody></table>
  </section>;
}
