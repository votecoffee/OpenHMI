import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Puck, Render } from '@puckeditor/core';
import '@puckeditor/core/no-external.css';
import '../openhmi/web/style.css';
import './hmi.css';
import './project-tools.css';
import { Live, ScreenControls, createConfig } from './controls.jsx';
import { toEditor, toProject } from './model.mjs';
import { api, json } from './api.mjs';
import { Localization } from './localization.jsx';
import { ProjectSettings, getSettings } from './project-settings.jsx';
import { AlarmConsole } from './alarm-console.jsx';

const editorOverrides = { headerActions: () => null };

function Builder({ initial, config, catalog }) {
  const initialData = useMemo(() => toEditor(initial.draft), [initial.draft]);
  const revision = useRef(initial.draft_revision);
  const latest = useRef(toEditor(initial.draft));
  const chain = useRef(Promise.resolve(true));
  const timer = useRef();
  const blocked = useRef(false);
  const [message, setMessage] = useState(`Draft ${initial.draft_revision} saved. Live values are visible while editing.`);
  const [busy, setBusy] = useState(false);
  const [previewControls, setPreviewControls] = useState(initial.draft.controls);
  const metadata = useRef(getSettings(initial.draft));
  const [settings, setSettings] = useState(metadata.current);
  const [tab, setTab] = useState('screen');
  const [previewProject, setPreviewProject] = useState({ ...initial.draft, ...metadata.current });

  useEffect(() => () => clearTimeout(timer.current), []);

  function save(data, projectSettings = metadata.current) {
    chain.current = chain.current.then(async () => {
      if (blocked.current) return false;
      try {
        const state = await api('/api/project/draft', json('PUT', {
          expected_revision: revision.current, project: toProject(data, projectSettings),
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
    setPreviewProject(toProject(data, metadata.current));
    clearTimeout(timer.current);
    if (blocked.current) return;
    setMessage('Draft changed. Saving...');
    timer.current = setTimeout(() => save(data), 600);
  }

  function settingsChanged(next) {
    metadata.current = next;
    setSettings(next);
    setPreviewProject(toProject(latest.current, next));
    clearTimeout(timer.current);
    if (blocked.current) return;
    setMessage('Draft changed. Saving...');
    timer.current = setTimeout(() => save(latest.current, next), 600);
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

  return <Localization project={previewProject}><ScreenControls.Provider value={previewControls}>
    <div className="builder-guide"><p>Drop a control, select a tag, and apply your screen. No code required.</p>
      <div><button onClick={() => { clearTimeout(timer.current); save(latest.current); }}>Save draft</button>
        <button className="apply-button" onClick={apply} disabled={busy}>{busy ? 'Applying...' : 'Apply live'}</button>
        <a href="/runtime" target="_blank" rel="noreferrer">Open live screen ↗</a></div></div>
    <p role="status" aria-label="Draft status" className="save-status">{message}</p>
    <nav className="project-tabs" aria-label="Project tools">{[['screen', 'Screen'], ['languages', 'Languages'], ['alarms', 'Alarm setup']].map(([key, label]) =>
      <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {tab !== 'screen' && <ProjectSettings tab={tab} settings={settings} controls={previewControls} title={previewProject.title} catalog={catalog} onChange={settingsChanged} />}
    <div hidden={tab !== 'screen'}><Puck config={config} data={initialData} iframe={{ enabled: false }}
      headerTitle="Screen builder" headerPath="" height="calc(100vh - 182px)" onChange={changed}
      overrides={editorOverrides} /></div>
  </ScreenControls.Provider></Localization>;
}

const MemoBuilder = React.memo(Builder);

function App({ initial, catalog }) {
  const runtime = location.pathname !== '/';
  const config = useMemo(() => createConfig(catalog), [catalog]);
  const [live, setLive] = useState({ values: {}, connected: false, alarms: null, alarmConnected: false });
  const [active, setActive] = useState({ revision: initial.active_revision, project: initial.active });
  const [screenConnected, setScreenConnected] = useState(true);
  useEffect(() => {
    let stopped = false;
    let timer;
    async function tick() {
      const [tags, alarms] = await Promise.allSettled([api('/api/tags'), api('/api/alarms')]);
      if (!stopped) setLive({ values: tags.status === 'fulfilled' ? tags.value.values : {}, connected: tags.status === 'fulfilled',
        alarms: alarms.status === 'fulfilled' ? alarms.value : null, alarmConnected: alarms.status === 'fulfilled' });
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
      <a href="/runtime">Overview</a><a href="/alarms">Alarms</a><a href="/">Edit screen</a></div>{!screenConnected && <p role="alert">Screen updates unavailable. Showing the last applied layout.</p>}
      <Localization project={active.project}>{location.pathname === '/alarms' ? <AlarmConsole /> : <ScreenControls.Provider value={active.project.controls}><Render config={config} data={toEditor(active.project)} /></ScreenControls.Provider>}</Localization></main> : <MemoBuilder initial={initial} config={config} catalog={catalog} />}
  </Live.Provider>;
}

try {
  const [initial, catalog] = await Promise.all([api('/api/project'), api('/api/catalog')]);
  createRoot(document.getElementById('root')).render(<App initial={initial} catalog={catalog} />);
} catch (error) {
  document.getElementById('root').textContent = `Unable to open project: ${error.message}. Refresh to retry.`;
}
