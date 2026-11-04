import React, { useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Puck, Render } from '@puckeditor/core';
import '@puckeditor/core/no-external.css';
import '../openhmi/web/style.css';
import './hmi.css';
import './project-tools.css';
import './recipes.css';
import './security.css';
import './engineering.css';
import './operations.css';
import { ActivityConsole, DiagnosticsConsole, CommandConsole } from './operations.jsx';
import { Live, ScreenControls, createConfig } from './controls.jsx';
import { toEditor, toProject, projectScreens, scopedScreen } from './model.mjs';
import { EngineeringSettings, engineeringCatalog } from './engineering.jsx';
import { WorkspacePage } from './workspace.jsx';
import { api, json } from './api.mjs';
import { Localization } from './localization.jsx';
import { ProjectSettings, getSettings } from './project-settings.jsx';
import { AlarmConsole } from './alarm-console.jsx';
import { RecipeWorkspace } from './recipes.jsx';
import { SecurityContext, SecurityBar, SecurityAdmin, allowed } from './security.jsx';

const editorOverrides = { headerActions: () => null };

function Builder({ initial, catalog }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext);
  const canEdit = allowed(session, 'project.edit');
  const [scope, setScope] = useState('overview');
  const [previewRoot, setPreviewRoot] = useState('');
  const scopeRef = useRef('overview');
  const document = useRef(initial.draft);
  const [initialData, setInitialData] = useState(toEditor(initial.draft));
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
  const template = settings.faceplates.find(item => `faceplate:${item.id}` === scope);
  const dynamicCatalog = useMemo(() => engineeringCatalog(catalog, settings, template), [catalog, settings, template]);
  const config = useMemo(() => createConfig(dynamicCatalog), [dynamicCatalog]);
  useEffect(() => { window.dispatchEvent(new CustomEvent('openhmi-editor-scope', { detail: { screen: scope.startsWith('faceplate:') ? 'overview' : scope, root: scope.startsWith('faceplate:') ? previewRoot : '' } })); }, [scope, previewRoot]);
  const previewValues = { ...live.values };
  if (template && previewRoot) for (const member of Object.keys(template.members)) previewValues[`$.${member}`] = live.values[`${previewRoot}.${member}`];

  function compose(data, projectSettings = metadata.current) {
    const content = toProject(data);
    const next = { ...document.current, ...projectSettings };
    if (scopeRef.current === 'overview') Object.assign(next, { title: content.title, columns: content.columns, controls: content.controls });
    else if (scopeRef.current.startsWith('faceplate:')) next.faceplates = next.faceplates.map(item => `faceplate:${item.id}` === scopeRef.current ? { ...item, name: content.title, controls: content.controls } : item);
    else next.screens = next.screens.map(item => item.id === scopeRef.current ? { ...item, title: content.title, columns: content.columns, controls: content.controls } : item);
    return next;
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  function save(data, projectSettings = metadata.current) {
    const candidate = compose(data, projectSettings);
    document.current = candidate;
    metadata.current = getSettings(candidate);
    if (!canEdit) { setMessage('Local draft retained. Sign in with project editing permission to save.'); return Promise.resolve(false); }
    chain.current = chain.current.then(async () => {
      if (blocked.current) return false;
      try {
        const state = await api('/api/project/draft', json('PUT', {
          expected_revision: revision.current, project: candidate,
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
    const next = compose(data);
    setPreviewProject(next);
    metadata.current = getSettings(next);
    clearTimeout(timer.current);
    if (blocked.current) return;
    setMessage('Draft changed. Saving...');
    timer.current = setTimeout(() => save(data), 600);
  }

  function settingsChanged(next) {
    metadata.current = next;
    setSettings(next);
    setPreviewProject(compose(latest.current, next));
    clearTimeout(timer.current);
    if (blocked.current) return;
    setMessage('Draft changed. Saving...');
    timer.current = setTimeout(() => save(latest.current, next), 600);
  }

  async function editScope(identifier) {
    clearTimeout(timer.current);
    if (!await save(latest.current)) return;
    const target = identifier.startsWith('faceplate:') ? document.current.faceplates.find(item => `faceplate:${item.id}` === identifier) : projectScreens(document.current).find(item => item.id === identifier);
    if (!target) return;
    scopeRef.current = identifier; setScope(identifier);
    const data = toEditor(identifier.startsWith('faceplate:') ? { title: target.name, columns: 2, controls: target.controls } : target);
    latest.current = data; setInitialData(data); setPreviewControls(target.controls); setTab('screen');
    setSettings(getSettings(document.current));
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

  return <Localization project={previewProject}><Live.Provider value={{ ...live, values: previewValues, project: previewProject }}><ScreenControls.Provider value={previewControls}>
    <div className="builder-guide"><p>Drop a control, select a tag, and apply your screen. No code required.</p>
      <div><button disabled={!canEdit} onClick={() => { clearTimeout(timer.current); save(latest.current); }}>Save draft</button>
        <button className="apply-button" onClick={apply} disabled={busy || !canEdit}>{busy ? 'Applying...' : 'Apply live'}</button>
        <a href="/runtime" target="_blank" rel="noreferrer">Open live screen ↗</a><a href="/projects">Projects</a><span>Editing: {scope}</span></div></div>
    <p role="status" aria-label="Draft status" className="save-status">{message}</p>
    {template && <label className="builder-guide">Faceplate preview UDT<select value={previewRoot} onChange={event => setPreviewRoot(event.target.value)}><option value="">Choose live UDT instance</option>{settings.tags.filter(tag => tag.type === 'struct' && (!template.udt_type || template.udt_type === tag.udt_type)).map(tag => <option key={tag.name}>{tag.name}</option>)}</select></label>}
    <nav className="project-tabs" aria-label="Project tools">{[['screen', 'Screen'], ['screens', 'Screens'], ['connections', 'Connections'], ['tags', 'Tags'], ['faceplates', 'Faceplates'], ['history', 'History'], ['commands', 'Commands'], ['languages', 'Languages'], ['alarms', 'Alarm setup']].map(([key, label]) =>
      <button key={key} aria-pressed={tab === key} onClick={() => { clearTimeout(timer.current); save(latest.current); setSettings(metadata.current); setTab(key); }}>{label}</button>)}<a href="/recipe-editor">Recipes</a></nav>
    {['languages', 'alarms'].includes(tab) && <ProjectSettings tab={tab} settings={settings} controls={previewControls} title={previewProject.title} catalog={dynamicCatalog} onChange={settingsChanged} />}
    {['screens', 'connections', 'tags', 'faceplates', 'history', 'commands'].includes(tab) && <EngineeringSettings key={tab} tab={tab} settings={settings} onChange={settingsChanged} editScope={editScope} catalog={dynamicCatalog} />}
    <div hidden={tab !== 'screen'}><Puck key={scope} config={config} data={initialData} iframe={{ enabled: false }}
      headerTitle="Screen builder" headerPath="" height="calc(100vh - 182px)" onChange={changed}
      overrides={editorOverrides} /></div>
  </ScreenControls.Provider></Live.Provider></Localization>;
}

const MemoBuilder = React.memo(Builder);

function App({ initial, catalog }) {
  const runtime = location.pathname !== '/';
  const [live, setLive] = useState({ values: {}, connected: false, alarms: null, alarmConnected: false });
  const [active, setActive] = useState({ revision: initial.active_revision, project: initial.active, project_instance: initial.project_instance });
  const [projectChanged, setProjectChanged] = useState(false);
  const [screenId, setScreenId] = useState(new URLSearchParams(location.search).get('screen') || 'overview');
  const [editorSubscription, setEditorSubscription] = useState({ screen: 'overview', root: '' });
  const [popups, setPopups] = useState([]);
  const clientId = useRef(crypto.randomUUID());
  const currentScreen = scopedScreen(active.project, screenId);
  const runtimeCatalog = useMemo(() => engineeringCatalog(catalog, getSettings(active.project)), [catalog, active.project]);
  const config = useMemo(() => createConfig(runtimeCatalog), [runtimeCatalog]);
  const updateRate = useRef(500);
  updateRate.current = runtime ? Math.min(currentScreen.update_ms || 500, ...popups.map(id => projectScreens(active.project).find(item => item.id === id)?.update_ms || 500)) : 500;
  const [screenConnected, setScreenConnected] = useState(true);
  const [session, setSession] = useState(null);
  const editorStarted = useRef(false);
  if (allowed(session, 'project.edit')) editorStarted.current = true;
  async function refreshSession() { try { setSession(await api('/api/security/session')); } catch { setSession(null); } }
  useEffect(() => {
    function navigate(event) {
      const { mode, screen } = event.detail;
      if (mode === 'navigate') { setScreenId(screen); setPopups([]); history.replaceState(null, '', `/runtime?screen=${encodeURIComponent(screen)}`); }
      if (mode === 'popup') setPopups(previous => [...new Set([...previous, screen])].slice(-5));
      if (mode === 'close_popup') setPopups(previous => previous.slice(0, -1));
    }
    window.addEventListener('openhmi-navigate', navigate);
    const editor = event => setEditorSubscription(event.detail);
    window.addEventListener('openhmi-editor-scope', editor);
    return () => { window.removeEventListener('openhmi-navigate', navigate); window.removeEventListener('openhmi-editor-scope', editor); };
  }, []);
  const leasedScreens = runtime ? location.pathname === '/runtime' ? [currentScreen.id, ...popups].join(',') : '' : editorSubscription.screen;
  useEffect(() => {
    let stopped = false, timer;
    async function heartbeat() { try { await api('/api/subscriptions', json('POST', { client: clientId.current, screens: leasedScreens ? leasedScreens.split(',') : [], preview_root: runtime ? '' : editorSubscription.root })); } catch {} if (!stopped) timer = setTimeout(heartbeat, 5000); }
    heartbeat(); return () => { stopped = true; clearTimeout(timer); };
  }, [leasedScreens, editorSubscription.root]);
  useEffect(() => {
    let stopped = false;
    let timer;
    async function tick() {
      const [tags, alarms, recipe, identity] = await Promise.allSettled([api('/api/tags'), api('/api/alarms'), api('/api/recipes/selected'), api('/api/security/session')]);
      if (!stopped) setSession(identity.status === 'fulfilled' ? identity.value : null);
      if (!stopped) setLive({ values: tags.status === 'fulfilled' ? tags.value.values : {}, connected: tags.status === 'fulfilled',
        samples: tags.status === 'fulfilled' ? tags.value.samples : {}, driver: tags.status === 'fulfilled' ? tags.value.driver : null,
        connections: tags.status === 'fulfilled' ? tags.value.connections || [] : [], plcHold: tags.status === 'fulfilled' && tags.value.plc_hold,
        alarms: alarms.status === 'fulfilled' ? alarms.value : null, alarmConnected: alarms.status === 'fulfilled',
        recipeSelection: recipe.status === 'fulfilled' ? recipe.value : null, recipeConnected: recipe.status === 'fulfilled' });
      {
        try {
          const next = await api('/api/project/active');
          if (next.project_instance && next.project_instance !== initial.project_instance) {
            if (runtime) { location.replace(location.pathname === '/projects' ? '/' : location.href); return; }
            else setProjectChanged(true);
          }
          if (!stopped) { setActive(previous => previous.revision === next.revision ? previous : next); setScreenConnected(true); }
        } catch { if (!stopped) setScreenConnected(false); }
      }
      if (!stopped) timer = setTimeout(tick, updateRate.current);
    }
    tick();
    return () => { stopped = true; clearTimeout(timer); };
  }, [runtime]);
  return <SecurityContext.Provider value={{ session, refreshSession }}><Live.Provider value={{ ...live, project: active.project }}>
    <header className="app-header"><a className="brand" href="/">OpenHMI</a><span>Build it visually. Extend it with Python.</span>
      <span className={`connection ${live.connected ? 'connected' : ''}`}>{live.connected ? live.driver === 'logix' ? live.connections.some(connection => connection.connected) ? 'PLC data available' : 'PLC disconnected' : 'Simulator connected' : 'Simulator disconnected'}</span></header>
    <SecurityBar session={session} refresh={refreshSession} />
    {projectChanged && <p role="alert" className="save-status">A different project was opened. Saves from this editor are blocked; copy any unsaved work before reloading. <button onClick={() => location.reload()}>Reload opened project</button></p>}
    {live.plcHold && <p role="status" className="save-status">Imported PLC connections are held. Review the project and use Apply live to enable its configured connections.</p>}
    {runtime ? <main className="runtime"><div className="runtime-bar"><span>Live screen / revision {active.revision}</span>
      <a href="/runtime">Overview</a><a href="/alarms">Alarms</a><a href="/recipes">Recipes</a><a href="/commands">Commands</a><a href="/activity">Activity</a><a href="/diagnostics">Diagnostics</a><a href="/projects">Projects</a><a href="/">Edit screen</a></div>{!screenConnected && <p role="alert">Screen updates unavailable. Showing the last applied layout.</p>}
      <Localization project={active.project}>{location.pathname === '/commands' ? <CommandConsole /> : location.pathname === '/activity' ? <ActivityConsole /> : location.pathname === '/diagnostics' ? <DiagnosticsConsole /> : location.pathname === '/projects' ? <WorkspacePage key={session?.user?.name || 'anonymous'} /> : location.pathname === '/security' ? <SecurityAdmin /> : ['/recipes', '/recipe-editor'].includes(location.pathname) ? <RecipeWorkspace edit={location.pathname === '/recipe-editor'} catalog={runtimeCatalog} /> : location.pathname === '/alarms' ? <AlarmConsole /> : <>
        <nav className="screen-navigation" aria-label="HMI screens">{projectScreens(active.project).filter(screen => !screen.popup).map(screen => <button key={screen.id} aria-pressed={currentScreen.id === screen.id} onClick={() => { setScreenId(screen.id); history.replaceState(null, '', `/runtime?screen=${encodeURIComponent(screen.id)}`); }}>{screen.title}</button>)}</nav>
        <ScreenControls.Provider value={currentScreen.controls}><Render config={config} data={toEditor(currentScreen)} /></ScreenControls.Provider>
        {popups.map((id, index) => { const screen = scopedScreen(active.project, id); return <div className="hmi-popup-shade" key={id} style={{ zIndex: 10000 + index }}><section className="hmi-popup" role="dialog" aria-modal="true" aria-label={screen.title}><header><strong>{screen.title}</strong><button onClick={() => setPopups(previous => previous.filter(item => item !== id))}>Close popup</button></header><ScreenControls.Provider value={screen.controls}><Render config={config} data={toEditor(screen)} /></ScreenControls.Provider></section></div>; })}
      </>}</Localization></main> : editorStarted.current ? <MemoBuilder initial={initial} catalog={catalog} /> : <main className="security-admin"><p>Sign in with a group that has project.edit permission to edit this HMI.</p><a href="/runtime">Open live screen</a></main>}
  </Live.Provider></SecurityContext.Provider>;
}

try {
  const [initial, catalog] = await Promise.all([api('/api/project'), api('/api/catalog')]);
  createRoot(document.getElementById('root')).render(<App initial={initial} catalog={catalog} />);
} catch (error) {
  document.getElementById('root').textContent = `Unable to open project: ${error.message}. Refresh to retry.`;
}
