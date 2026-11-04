import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Puck, Render } from '@puckeditor/core';
import '@puckeditor/core/no-external.css';
import '../openhmi/web/style.css';
import './hmi.css';
import { Live, ScreenControls, createConfig } from './controls.jsx';
import { toEditor, toProject } from './model.mjs';
import { api, json } from './api.mjs';

const editorOverrides = { headerActions: () => null };

function Builder({ initial, config }) {
  const initialData = useMemo(() => toEditor(initial.draft), [initial.draft]);
  const revision = useRef(initial.draft_revision);
  const latest = useRef(toEditor(initial.draft));
  const chain = useRef(Promise.resolve(true));
  const timer = useRef();
  const blocked = useRef(false);
  const [message, setMessage] = useState(`Draft ${initial.draft_revision} saved. Live values are visible while editing.`);
  const [busy, setBusy] = useState(false);
  const [previewControls, setPreviewControls] = useState(initial.draft.controls);

  useEffect(() => () => clearTimeout(timer.current), []);

  function save(data) {
    chain.current = chain.current.then(async () => {
      if (blocked.current) return false;
      try {
        const state = await api('/api/project/draft', json('PUT', {
          expected_revision: revision.current, project: toProject(data),
        }));
        revision.current = state.draft_revision;
        setMessage(`Draft ${state.draft_revision} saved. Apply live to update runtime viewers.`);
        return true;
      } catch (error) {
        if (error.conflict) blocked.current = true;
        setMessage(`Not saved: ${error.message}${error.conflict ? ' Your changes remain in this editor; copy them before reloading.' : ''}`);
        return false;
      }
    });
    return chain.current;
  }

  function changed(data) {
    latest.current = data;
    setPreviewControls(toProject(data).controls);
    clearTimeout(timer.current);
    if (blocked.current) return;
    setMessage('Draft changed. Saving...');
    timer.current = setTimeout(() => save(data), 600);
  }

  async function apply() {
    clearTimeout(timer.current);
    setBusy(true);
    const candidate = latest.current;
    try {
      if (!await save(candidate)) return;
      const state = await api('/api/project/apply', json('POST', { expected_revision: revision.current }));
      setMessage(`Applied live revision ${state.active_revision}. Existing viewers update automatically.`);
    } catch (error) {
      if (error.conflict) blocked.current = true;
      setMessage(`Not applied: ${error.message}`);
    } finally { setBusy(false); }
  }

  return <ScreenControls.Provider value={previewControls}>
    <div className="builder-guide"><p>Drop a control, select a tag, and apply your screen. No code required.</p>
      <div><button onClick={() => { clearTimeout(timer.current); save(latest.current); }}>Save draft</button>
        <button className="apply-button" onClick={apply} disabled={busy}>{busy ? 'Applying...' : 'Apply live'}</button>
        <a href="/runtime" target="_blank" rel="noreferrer">Open live screen ↗</a></div></div>
    <p role="status" aria-label="Draft status" className="save-status">{message}</p>
    <Puck config={config} data={initialData} iframe={{ enabled: false }}
      headerTitle="Screen builder" headerPath="" height="calc(100vh - 182px)" onChange={changed}
      overrides={editorOverrides} />
  </ScreenControls.Provider>;
}

const MemoBuilder = React.memo(Builder);

function App({ initial, catalog }) {
  const runtime = location.pathname === '/runtime';
  const config = useMemo(() => createConfig(catalog), [catalog]);
  const [live, setLive] = useState({ values: {}, connected: false });
  const [active, setActive] = useState({ revision: initial.active_revision, project: initial.active });
  const [screenConnected, setScreenConnected] = useState(true);
  useEffect(() => {
    let stopped = false;
    let timer;
    async function tick() {
      try {
        const tags = await api('/api/tags');
        if (!stopped) setLive({ values: tags.values, connected: true });
      } catch {
        if (!stopped) setLive({ values: {}, connected: false });
      }
      if (runtime) {
        try {
          const next = await api('/api/project/active');
          if (!stopped) { setActive(next); setScreenConnected(true); }
        } catch { if (!stopped) setScreenConnected(false); }
      }
      if (!stopped) timer = setTimeout(tick, 500);
    }
    tick();
    return () => { stopped = true; clearTimeout(timer); };
  }, [runtime]);
  return <Live.Provider value={live}>
    <header className="app-header"><a className="brand" href="/">OpenHMI</a><span>Build it visually. Extend it with Python.</span>
      <span className={`connection ${live.connected ? 'connected' : ''}`}>{live.connected ? 'Simulator connected' : 'Simulator disconnected'}</span></header>
    {runtime ? <main className="runtime"><div className="runtime-bar"><span>Live screen / revision {active.revision}</span>
      <a href="/">Edit screen</a></div>{!screenConnected && <p role="alert">Screen updates unavailable. Showing the last applied layout.</p>}
      <ScreenControls.Provider value={active.project.controls}><Render config={config} data={toEditor(active.project)} /></ScreenControls.Provider></main> : <MemoBuilder initial={initial} config={config} />}
  </Live.Provider>;
}

try {
  const [initial, catalog] = await Promise.all([api('/api/project'), api('/api/catalog')]);
  createRoot(document.getElementById('root')).render(<App initial={initial} catalog={catalog} />);
} catch (error) {
  document.getElementById('root').textContent = `Unable to open project: ${error.message}. Refresh to retry.`;
}
