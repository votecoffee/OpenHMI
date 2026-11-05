import React, { useEffect, useState } from 'react';
import { api, json } from './api.mjs';

export function PublicationStation({ session }) {
  const [client] = useState(() => { try { let value = sessionStorage.getItem('openhmi.station'); if (!value) sessionStorage.setItem('openhmi.station', value = crypto.randomUUID()); return value; } catch { return crypto.randomUUID(); } });
  const [status, setStatus] = useState(null), [active, setActive] = useState(false), [message, setMessage] = useState('');
  useEffect(() => {
    let stopped = false, timer;
    async function refresh() {
      try { const state = active && session?.user ? await api('/api/security/publication/claim', json('POST', { client })) : await api('/api/security/publication'); if (!stopped) { setStatus(state); if (active && state.owner !== client) setActive(false); } }
      catch (error) { if (!stopped) { setMessage(error.message); setActive(false); } }
      if (!stopped) timer = setTimeout(refresh, 2000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [active, client, session?.user?.name]);
  if (!status?.configured) return null;
  const permitted = session?.user?.permissions.includes('identity.publish');
  return <section aria-label="PLC login publication"><span>PLC identity: {status.status}{status.status === 'published' ? ` · ${status.username || 'signed out'} · privileges ${status.privileges}` : ''}{status.error ? ` · ${status.error}` : ''}</span>
    <button disabled={!permitted} onClick={async () => { try { const next = await api(`/api/security/publication/${active ? 'release' : 'claim'}`, json('POST', { client })); setStatus(next); setActive(!active); setMessage(''); } catch (error) { setMessage(error.message); } }}>{active ? 'Stop publishing this station' : 'Publish this station login'}</button>{message && <span role="status">{message}</span>}</section>;
}
