import React, { useContext, useEffect, useState } from 'react';
import { isDiagnosticsSnapshot, diagnosticsExportPath, readDiagnostics } from './diagnostics-api.mjs';
import { SecurityContext, canInspect } from './security.jsx';

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

const diagnosticQualities = {
  all: 'All qualities', 'non-good': 'Needs attention', bad: 'Bad', stale: 'Stale', pending: 'Pending', good: 'Good',
};

export function DiagnosticsConsole() {
  const { session } = useContext(SecurityContext);
  const permitted = canInspect(session, 'diagnostics.view');
  const [criteria, setCriteria] = useState(() => {
    const query = new URLSearchParams(location.search);
    const connection = query.get('connection') || '';
    const quality = query.get('quality');
    return {
      search: (query.get('search') || '').slice(0, 100),
      quality: Object.hasOwn(diagnosticQualities, quality) ? quality : 'all',
      connection: /^(?:[A-Za-z][A-Za-z0-9_-]{0,59}|:local)$/.test(connection) ? connection : '',
    };
  });
  const [filter, setFilter] = useState(criteria.search);
  const [quality, setQuality] = useState(criteria.quality);
  const [connection, setConnection] = useState(criteria.connection);
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState(null);
  const current = result?.criteria === criteria && result.offset === offset ? result : null;
  const { data, message, receivedAt } = current ?? {};
  const connections = result?.data?.connections ?? [];
  useEffect(() => {
    if (!permitted) { setResult(null); return; }
    let stopped = false, timer;
    async function tick() {
      try {
        const snapshot = await readDiagnostics(criteria, offset);
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
    <h2>Tag quality</h2><form onSubmit={event => { event.preventDefault(); setCriteria({ search: filter, quality, connection }); setOffset(0); }}>
      <label>Tag filter<input maxLength={100} value={filter} onChange={event => setFilter(event.target.value)} /></label>
      <label>Sample quality<select value={quality} onChange={event => setQuality(event.target.value)}>
        {Object.entries(diagnosticQualities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label>Tag connection<select value={connection} onChange={event => setConnection(event.target.value)}>
        <option value="">All connections</option><option value=":local">Local HMI</option>
        {connections.map(route => <option key={route.id} value={route.id}>{route.name} ({route.id})</option>)}
        {connection && connection !== ':local' && !connections.some(route => route.id === connection)
          && <option value={connection}>{connection}</option>}
      </select></label><button>Filter diagnostic tags</button>
    </form>
    <div className="operations-actions"><button disabled={!offset} onClick={() => setOffset(0)}>First tags</button><button disabled={!!message || data?.next_offset == null} onClick={() => setOffset(data.next_offset)}>More tags</button><a href={diagnosticsExportPath(criteria)}>Export diagnostics JSON</a></div>
    {data && <p>{data.total_tags} matching logical tags. Values are omitted from this diagnostic export.</p>}
    <table className="diagnostics-tags"><thead><tr><th>Tag / source</th><th>Type</th><th>Quality</th><th>Age (s)</th><th>Acquisition time / error</th></tr></thead><tbody>{data?.tags.map(tag => <tr key={tag.name}><td>{tag.name}<br /><small>{tag.connection || 'Local'} · {tag.address}</small></td><td>{tag.type}</td><td><strong>{tag.quality}</strong></td><td>{tag.age_seconds == null ? '—' : tag.age_seconds.toFixed(2)}</td><td>{tag.timestamp ? new Date(tag.timestamp).toLocaleString() : 'No sample'}<br />{tag.error}</td></tr>)}</tbody></table>
  </section>;
}
