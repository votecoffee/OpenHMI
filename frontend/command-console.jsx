import React, { useContext, useEffect, useState } from 'react';
import { api } from './api.mjs';
import { commandHistoryPath, commandTransactionPath } from './command-api.mjs';
import { commandStates, isCommandPage, isCommandRecord } from './command-status.mjs';
import { SecurityContext, allowed } from './security.jsx';

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
  const endpoint = exact ? commandTransactionPath(identifier) : commandHistoryPath({ ...applied, before });
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
    {exact && data?.items.length > 0 && <p><a href={commandTransactionPath(identifier, true)}>Download transaction JSON</a></p>}
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
