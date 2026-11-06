import React, { useContext, useEffect, useState } from 'react';
import { api } from './api.mjs';
import { commandStates, isCommandPage, isCommandRecord } from './command-status.mjs';
import { SecurityContext, allowed } from './security.jsx';

function canInspect(session, permission) {
  return allowed(session, permission) || !!session?.user?.permissions.includes('security.manage');
}

export function CommandConsole() {
  const { session } = useContext(SecurityContext);
  const permitted = allowed(session, 'runtime.operate');
  const identifier = new URLSearchParams(location.search).get('transaction');
  const exact = identifier !== null;
  const valid = !exact || /^[1-9]\d{0,18}$/.test(identifier);
  const [filters, setFilters] = useState({ command: '', state: '' });
  const [applied, setApplied] = useState(filters);
  const [response, setResponse] = useState(null);
  const [before, setBefore] = useState(null);
  const parameters = new URLSearchParams({ limit: '50' });
  if (applied.command) parameters.set('command_id', applied.command);
  if (applied.state) parameters.set('state', applied.state);
  if (before) parameters.set('before_id', before);
  const endpoint = exact ? `/api/commands/${identifier}` : `/api/commands?${parameters}`;
  const { data, error, receivedAt } = response?.endpoint === endpoint ? response : {};
  useEffect(() => {
    if (!permitted || !valid) { setResponse(null); return; }
    let stopped = false, timer;
    async function refresh() {
      try {
        const result = await api(endpoint);
        const readable = exact ? isCommandRecord(result) && String(result.id) === identifier : isCommandPage(result);
        if (!readable) throw new Error('Invalid command status response');
        if (!stopped) setResponse({ endpoint, data: exact ? { items: [result] } : result, receivedAt: new Date() });
      } catch (problem) {
        const discard = [401, 403].includes(problem.status) || (exact && problem.status === 404);
        if (!stopped) setResponse(previous => {
          const retain = !discard && previous?.endpoint === endpoint;
          return { ...(retain ? previous : { endpoint }), error: problem.message };
        });
      }
      if (!stopped) timer = setTimeout(refresh, 1000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [permitted, valid, endpoint, exact, identifier]);
  if (!permitted) return <p>Sign in with runtime operation permission to inspect command transactions.</p>;
  return <section className="engineering operations" aria-label="PLC command transactions"><h1>PLC command transactions</h1>
    {exact && <p><a href="/commands">All command transactions</a></p>}
    {exact && valid && <h2>Transaction #{identifier}</h2>}
    {exact && data?.items.length > 0 && <p><a href={`${endpoint}?download=true`}>Download transaction JSON</a></p>}
    {!valid && <p role="alert">Enter a valid command transaction ID.</p>}
    <p>Staging means recipe parameters are being written; commit has not been sent. Requested means request/commit dispatch started. Accepted means the PLC acknowledged this sequence. Completed / failed requires a matching PLC completion and result. Timeout is uncertain; it does not cancel or replay the request.</p>
    {!exact && <form className="operations-filters" onSubmit={event => {
      event.preventDefault(); setApplied({ ...filters, command: filters.command.trim() }); setBefore(null);
    }}>
      <label>Command ID<input value={filters.command} maxLength={60}
        onChange={event => setFilters({ ...filters, command: event.target.value })} /></label>
      <label>Transaction state<select aria-label="Transaction state" value={filters.state} onChange={event => setFilters({ ...filters, state: event.target.value })}>
        <option value="">All states</option>
        {['unresolved', ...commandStates].map(state => <option key={state} value={state}>{state === 'unresolved' ? 'All unresolved' : state}</option>)}
      </select></label>
      <button>Apply command filters</button>
    </form>}
    {error && <p role="alert">Command status unavailable. {error}
      {data && <> Showing last received command status from {receivedAt.toLocaleTimeString()}.</>}</p>}
    <table className="activity-table"><thead><tr><th>Transaction / command</th><th>Sequence / state</th><th>Result</th><th>Evidence</th></tr></thead><tbody>{data?.items.map(item => <tr key={item.id}>
      <td>{exact ? `#${item.id}` : <a href={`/commands?transaction=${item.id}`}>#{item.id}</a>} · {item.command_id}<br /><small>{item.created_at}</small></td><td>{item.sequence} · {item.state}</td><td>{item.result_code ?? 'Not completed'}</td><td>
        <details open={exact || undefined}><summary>Transaction details</summary><p>Operation {item.operation_id}</p><p>{item.error}</p>{item.events.map((event, i) => <p key={i}>{event.timestamp} · {event.state} · {event.detail}</p>)}<a href={`/activity?search=${encodeURIComponent(item.operation_id)}`}>Operator activity</a></details>
      </td></tr>)}</tbody></table>
    {data && !data.items.length && <p>{applied.command || applied.state ? 'No command transactions match these filters.' : 'No command transactions recorded.'}</p>}
    {!exact && <><button onClick={() => setBefore(null)}>Newest commands</button> <button disabled={!!error || !data?.has_more} onClick={() => setBefore(data.next_before_id)}>Older commands</button></>}
  </section>;
}

function activityParams(filters, before) {
  const query = new URLSearchParams();
  for (const key of ['actor', 'status', 'search']) if (filters[key]) query.set(key, filters[key]);
  for (const key of ['start', 'end']) if (filters[key]) query.set(key, new Date(filters[key]).toISOString());
  if (before) query.set('before_id', before);
  return query;
}

const activityOutcomes = ['pending', 'succeeded', 'denied', 'rejected', 'uncertain', 'interrupted'];

function isActivityRecord(item) {
  const isObject = value => value != null && typeof value === 'object' && !Array.isArray(value);
  const optionalText = value => value == null || typeof value === 'string';
  if (!isObject(item) || !activityOutcomes.includes(item.status) || !isObject(item.context)
    || !['operation_id', 'started_at', 'actor', 'provider', 'operation', 'entity', 'phase']
      .every(key => typeof item[key] === 'string')) return false;
  const { context, outcome } = item;
  return Array.isArray(item.groups) && item.groups.every(group => typeof group === 'string')
    && [item.finished_at, item.error, context.tag, context.target, context.before?.quality, context.before?.timestamp]
      .every(optionalText)
    && (outcome === null || (isObject(outcome) && optionalText(outcome.verification)
      && optionalText(outcome.observed_at) && (outcome.count == null || Number.isSafeInteger(outcome.count))));
}

function isActivityPage(page) {
  return Array.isArray(page?.items) && page.items.every(isActivityRecord) && typeof page.has_more === 'boolean'
    && (page.has_more ? Number.isSafeInteger(page.next_before_id) && page.next_before_id > 0 : page.next_before_id === null)
    && [page.pending_finalizations, page.retention_days, page.max_resolved_rows]
      .every(value => Number.isSafeInteger(value) && value >= 0);
}

export function ActivityConsole() {
  const { session } = useContext(SecurityContext);
  const permitted = canInspect(session, 'activity.view');
  const [filters, setFilters] = useState({ actor: '', status: '', search: new URLSearchParams(location.search).get('search') || '', start: '', end: '' });
  const [applied, setApplied] = useState(filters);
  const [before, setBefore] = useState(null);
  const [response, setResponse] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const endpoint = `/api/activity?${activityParams(applied, before)}`;
  const current = response?.endpoint === endpoint ? response : null;
  const { data, message, receivedAt } = current ?? {};
  useEffect(() => {
    if (!permitted) { setResponse(null); return; }
    let stopped = false, timer;
    async function tick() {
      let retry = !before;
      try {
        const result = await api(endpoint);
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
      <a href={`/api/activity.csv?${activityParams(applied)}`}>Export activity CSV</a></div>
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

const scanTimingLabels = [
  ['scan', 'Read cycle'], ['scan_lateness', 'Scan start lateness'],
  ['scan_queue', 'Scan worker queue'], ['route_lock_wait', 'Route lock wait'],
  ['adapter_read', 'Adapter read call'],
  ['cold_open', 'Initial connection'], ['reconnect_open', 'Reconnect'],
  ['recovery', 'Loss to first good read'],
];

function ConnectionTimings({ connection }) {
  const timings = connection.timings || {};
  if (!Object.keys(timings).length && !connection.route_failures) return '—';
  return <details><summary>Timing (ms)</summary>
    {scanTimingLabels.map(([key, label]) => {
      const timing = timings[key];
      return timing && <p key={key}><strong>{label}</strong><br />
        Last {timing.last_ms} · p50 {timing.p50_ms} · p95 {timing.p95_ms} · p99 {timing.p99_ms}<br />
        {timing.count} recent samples
      </p>;
    })}
    <p>Route failures: {connection.route_failures}</p>
  </details>;
}

const workerLabels = {
  acquisition: 'PLC acquisition', commands: 'Commands', alarms: 'Alarms',
  trends: 'Trend recording', historian: 'Historian', activity: 'Activity maintenance', identity: 'PLC identity',
};

function WorkerHealth({ workers }) {
  return <>
    <h2>Runtime workers</h2>
    <table aria-label="Runtime workers"><thead><tr><th>Worker</th><th>State</th><th>Last successful tick</th><th>Failures</th></tr></thead>
      <tbody>{workers.map(worker => <tr key={worker.id}>
        <th scope="row">{workerLabels[worker.id] || worker.id}</th>
        <td><strong>{worker.state}</strong>
          {worker.state === 'overdue' && <><br />Running for {worker.running_seconds.toFixed(1)} s</>}
          {worker.retry_in_seconds != null && <><br />Retry in {worker.retry_in_seconds.toFixed(1)} s</>}
        </td>
        <td>{worker.last_success_at ? new Date(worker.last_success_at).toLocaleString() : '—'}</td>
        <td>{worker.failures}{worker.last_error_type && <><br />Last error: {worker.last_error_type}</>}</td>
      </tr>)}</tbody>
    </table>
  </>;
}

function isDiagnosticsSnapshot(data, offset) {
  if (data?.offset !== offset || !Number.isSafeInteger(data.total_tags) || data.total_tags < 0
    || typeof data.plc_hold !== 'boolean' || (data.next_offset !== null
      && (!Number.isSafeInteger(data.next_offset) || data.next_offset <= offset))) return false;
  const textFields = (row, ...fields) => row != null && fields.every(field => typeof row[field] === 'string');
  const optionalText = value => value == null || typeof value === 'string';
  const optionalNumber = value => value == null || Number.isFinite(value);
  return Array.isArray(data.tags) && data.tags.every(tag => textFields(tag, 'name', 'address', 'type', 'quality')
      && optionalText(tag.connection) && optionalText(tag.timestamp) && optionalText(tag.error) && optionalNumber(tag.age_seconds))
    && Array.isArray(data.workers) && data.workers.every(worker => textFields(worker, 'id', 'state')
      && Number.isSafeInteger(worker.failures) && optionalText(worker.last_success_at) && optionalText(worker.last_error_type)
      && optionalNumber(worker.retry_in_seconds) && (worker.state !== 'overdue' || Number.isFinite(worker.running_seconds)))
    && Array.isArray(data.connections) && data.connections.every(route => textFields(route, 'id', 'name', 'path', 'state')
      && optionalText(route.error) && [route.read_calls, route.tags_read, route.route_failures].every(Number.isSafeInteger)
      && Array.isArray(route.groups) && route.groups.every(group => Number.isFinite(group?.rate_ms)
        && Array.isArray(group.addresses) && group.addresses.every(address => typeof address === 'string'))
      && route.timings && typeof route.timings === 'object' && !Array.isArray(route.timings)
      && Object.values(route.timings).every(timing => timing && ['last_ms', 'p50_ms', 'p95_ms', 'p99_ms', 'count']
        .every(field => Number.isFinite(timing[field]))));
}

export function DiagnosticsConsole() {
  const { session } = useContext(SecurityContext);
  const permitted = canInspect(session, 'diagnostics.view');
  const [filter, setFilter] = useState('');
  const [quality, setQuality] = useState('all');
  const [criteria, setCriteria] = useState({ search: '', quality: 'all' });
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState(null);
  const current = result?.criteria === criteria && result.offset === offset ? result : null;
  const { data, message, receivedAt } = current ?? {};
  useEffect(() => {
    if (!permitted) { setResult(null); return; }
    let stopped = false, timer;
    async function tick() {
      try {
        const query = new URLSearchParams({ ...criteria, offset });
        const snapshot = await api(`/api/diagnostics?${query}`);
        if (!isDiagnosticsSnapshot(snapshot, offset)) throw new Error('Invalid diagnostics response');
        if (!stopped) setResult({ criteria, offset, data: snapshot, receivedAt: new Date() });
      } catch (error) {
        const denied = error.status === 401 || error.status === 403;
        if (!stopped) setResult(previous => {
          const retain = !denied && previous?.criteria === criteria && previous.offset === offset;
          return { ...(retain ? previous : { criteria, offset }), message: error.message };
        });
      }
      if (!stopped) timer = setTimeout(tick, 2000);
    }
    tick(); return () => { stopped = true; clearTimeout(timer); };
  }, [permitted, criteria, offset]);
  if (!permitted) return <section className="engineering"><h1>Runtime diagnostics</h1><p>Sign in with diagnostics viewing permission to inspect runtime status.</p></section>;
  return <section className="engineering operations" aria-label="Runtime diagnostics"><h1>Runtime diagnostics</h1><p>Viewing diagnostics reads cached runtime state. It does not subscribe new tags or issue equipment writes.</p>
    {message && <p role="alert">Diagnostics unavailable. {message}
      {data && <> Showing last received diagnostics from {receivedAt.toLocaleTimeString()}.</>}</p>}
    {!current && <p role="status">Waiting for diagnostics.</p>}
    {data?.plc_hold && <p role="status">{message && 'Last received status: '}PLC connections are held until reviewed and applied.</p>}
    <h2>Connections and scans</h2><table><thead><tr><th>Connection / route</th><th>State</th><th>Read calls / addresses</th><th>Effective groups</th><th>Timing</th><th>Error</th></tr></thead><tbody>{data?.connections.map(connection => <tr key={connection.id}><td>{connection.name}<br />{connection.path}</td><td>{connection.state}{connection.state === 'scan overdue' && Number.isFinite(connection.scan_age_seconds) && <><br />{connection.scan_age_seconds.toFixed(1)} s in flight</>}</td><td>{connection.read_calls} / {connection.tags_read}</td><td>{connection.groups.map(group => <details key={group.rate_ms}><summary>{group.rate_ms} ms · {group.addresses.length} addresses</summary>{group.addresses.join(', ')}</details>)}</td><td><ConnectionTimings connection={connection} /></td><td>{connection.error || '—'}</td></tr>)}</tbody></table>
    {data && !data.connections.length && <p>No PLC connections are configured.</p>}
    <p>Scan intervals are best effort. Counters are pycomm3 read calls/requested addresses, not wire-packet measurements.</p>
    {!!data?.workers?.length && <WorkerHealth workers={data.workers} />}
    <h2>Tag quality</h2><form onSubmit={event => { event.preventDefault(); setCriteria({ search: filter, quality }); setOffset(0); }}>
      <label>Tag filter<input value={filter} onChange={event => setFilter(event.target.value)} /></label>
      <label>Sample quality<select value={quality} onChange={event => setQuality(event.target.value)}>
        <option value="all">All qualities</option><option value="non-good">Needs attention</option>
        <option value="bad">Bad</option><option value="stale">Stale</option><option value="pending">Pending</option><option value="good">Good</option>
      </select></label><button>Filter diagnostic tags</button>
    </form>
    <div className="operations-actions"><button disabled={!offset} onClick={() => setOffset(0)}>First tags</button><button disabled={!!message || data?.next_offset == null} onClick={() => setOffset(data.next_offset)}>More tags</button><a href={`/api/diagnostics.json?${new URLSearchParams(criteria)}`}>Export diagnostics JSON</a></div>
    {data && <p>{data.total_tags} matching logical tags. Values are omitted from this diagnostic export.</p>}
    <table className="diagnostics-tags"><thead><tr><th>Tag / source</th><th>Type</th><th>Quality</th><th>Age (s)</th><th>Acquisition time / error</th></tr></thead><tbody>{data?.tags.map(tag => <tr key={tag.name}><td>{tag.name}<br /><small>{tag.connection || 'Local'} · {tag.address}</small></td><td>{tag.type}</td><td><strong>{tag.quality}</strong></td><td>{tag.age_seconds == null ? '—' : tag.age_seconds.toFixed(2)}</td><td>{tag.timestamp ? new Date(tag.timestamp).toLocaleString() : 'No sample'}<br />{tag.error}</td></tr>)}</tbody></table>
  </section>;
}
