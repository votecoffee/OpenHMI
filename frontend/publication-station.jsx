import React, { useContext, useEffect, useState } from 'react';
import { api, json } from './api.mjs';
import { Live } from './live-quality.jsx';

function validateStatus(state) {
  if (typeof state?.configured !== 'boolean' || (state.owner !== null && typeof state.owner !== 'string')
    || !['disabled', 'pending', 'clearing', 'held', 'published', 'error'].includes(state.status)
    || (state.error != null && typeof state.error !== 'string')
    || (state.status === 'published' && (typeof state.username !== 'string' || !Number.isSafeInteger(state.privileges)))) {
    throw new Error('Invalid PLC identity status response');
  }
  return state;
}

export function PublicationStation({ session }) {
  const { project } = useContext(Live);
  const [client] = useState(() => { try { let value = sessionStorage.getItem('openhmi.station'); if (!value) sessionStorage.setItem('openhmi.station', value = crypto.randomUUID()); return value; } catch { return crypto.randomUUID(); } });
  const [status, setStatus] = useState(null);
  const [renewing, setRenewing] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const permitted = !!session?.user?.permissions.includes('identity.publish');
  useEffect(() => {
    if (busy) return;
    let stopped = false, timer;
    async function refresh() {
      try {
        const state = validateStatus(renewing && permitted
          ? await api('/api/security/publication/claim?renew=true', json('POST', { client }))
          : await api('/api/security/publication'));
        if (!stopped) {
          setStatus(state);
          setUnavailable(false);
          if (!permitted || state.owner !== client || !state.configured) setRenewing(false);
        }
      } catch (error) {
        if (!stopped) {
          setUnavailable(true);
          setRenewing(false);
          if ([401, 403].includes(error.status)) setStatus(null);
        }
      }
      if (!stopped) timer = setTimeout(refresh, 2000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [renewing, client, permitted, session?.user?.name, busy]);

  const owns = status?.owner === client;
  const blocked = !permitted || busy || unavailable || !status?.configured;
  async function change(action) {
    if (blocked) return;
    setBusy(true);
    setRenewing(false);
    setMessage('');
    try {
      const next = validateStatus(await api(`/api/security/publication/${action}`, json('POST', { client })));
      const claimed = action === 'claim';
      if ((next.owner === client) !== claimed) throw new Error('Station ownership was not confirmed');
      setStatus(next);
      setRenewing(claimed);
    } catch (error) {
      setUnavailable(true);
      setMessage(error.message);
      if ([401, 403].includes(error.status)) setStatus(null);
    } finally {
      setBusy(false);
    }
  }

  if (!(status?.configured ?? project?.identity_publication?.enabled)) return null;
  return <section aria-label="PLC login publication">
    {status && <span>{unavailable ? 'Last received PLC identity' : 'PLC identity'}: {status.status}
      {status.status === 'published' ? ` · ${status.username || 'signed out'} · privileges ${status.privileges}` : ''}
      {status.error ? ` · ${status.error}` : ''}</span>}
    {(!owns || !renewing) && <button disabled={blocked || (!!status?.owner && !owns)} onClick={() => change('claim')}>Publish this station login</button>}
    {owns && <button disabled={blocked} onClick={() => change('release')}>Stop publishing this station</button>}
    {unavailable && <span role="status">PLC identity status unavailable.</span>}
    {!unavailable && owns && !renewing && !busy && <span role="status">Automatic renewal paused. Publish this station login to resume.</span>}
    {message && <span role="status">{message}</span>}
  </section>;
}
