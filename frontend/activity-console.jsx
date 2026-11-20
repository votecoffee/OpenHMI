import React, { useContext, useEffect, useState } from 'react';
import { activityOutcomes, isActivityPage, activityHistoryPath, activityCsvPath, readActivity } from './activity-api.mjs';
import { SecurityContext, canInspect } from './security.jsx';

export function ActivityConsole() {
  const { session } = useContext(SecurityContext);
  const permitted = canInspect(session, 'activity.view');
  const [filters, setFilters] = useState({ actor: '', status: '', search: new URLSearchParams(location.search).get('search') || '', start: '', end: '' });
  const [applied, setApplied] = useState(filters);
  const [before, setBefore] = useState(null);
  const [response, setResponse] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const endpoint = activityHistoryPath(applied, before);
  const current = response?.endpoint === endpoint ? response : null;
  const { data, message, receivedAt } = current ?? {};
  useEffect(() => {
    if (!permitted) { setResponse(null); return; }
    let stopped = false, timer;
    async function tick() {
      let retry = !before;
      try {
        const result = await readActivity(applied, before);
        if (!isActivityPage(result)) throw new Error('Invalid activity response');
        if (!stopped) setResponse({ endpoint, data: result, receivedAt: new Date() });
      } catch (error) {
        retry = true;
        const denied = [401, 403].includes(error.status);
        if (!stopped) setResponse(previous => {
          const retain = !denied && previous?.endpoint === endpoint;
          return { ...(retain ? previous : { endpoint }), message: error.message };
        });
      }
      if (!stopped && retry) timer = setTimeout(tick, 5000);
    }
    tick(); return () => { stopped = true; clearTimeout(timer); };
  }, [permitted, endpoint, applied, before, refresh]);
  function value(key, text) { setFilters(previous => ({ ...previous, [key]: text })); }
  if (!permitted) return <section className="engineering"><h1>Operator activity</h1><p>Sign in with activity viewing permission to inspect the operator journal.</p></section>;
  return <section className="engineering operations" aria-label="Operator activity"><h1>Operator activity</h1>
    <p>Attempts are recorded before dispatch. Confirmed outcomes describe the indicated verification; tag readback or a Python callback return does not mean equipment completed a command.</p>
    <form className="operations-filters" onSubmit={event => { event.preventDefault(); setApplied({ ...filters }); setBefore(null); }}>
      <label>User<input value={filters.actor} onChange={event => value('actor', event.target.value)} /></label>
      <label>Outcome<select value={filters.status} onChange={event => value('status', event.target.value)}><option value="">All outcomes</option>{activityOutcomes.map(status => <option key={status}>{status}</option>)}</select></label>
      <label>Control, tag or operation ID<input value={filters.search} onChange={event => value('search', event.target.value)} /></label>
      <label>From<input type="datetime-local" value={filters.start} onChange={event => value('start', event.target.value)} /></label>
      <label>To<input type="datetime-local" value={filters.end} onChange={event => value('end', event.target.value)} /></label>
      <button>Apply activity filters</button>
    </form>
    <div className="operations-actions"><button onClick={() => { setBefore(null); setRefresh(value => value + 1); }}>Newest activity</button><button disabled={!!message || !data?.has_more} onClick={() => setBefore(data.next_before_id)}>Older activity</button>
      <a href={activityCsvPath(applied)}>Export activity CSV</a></div>
    {message && <p role="alert">Activity unavailable. {message}
      {data && <> Showing last received activity from {receivedAt.toLocaleTimeString()}.</>}</p>}
    {!current && <p role="status">Waiting for operator activity.</p>}
    {data?.pending_finalizations > 0 && <p role="status">{message && 'Last received status: '}{data.pending_finalizations} journal finalizations are pending. Commands are not replayed to repair the journal.</p>}
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
