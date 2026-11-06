import React, { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
import { Live, ConnectionStatus } from './live-quality.jsx';
import { ScreenControls, ScreenFrame, createConfig } from './controls.jsx';
import { CanvasEditor, CanvasSurface, initialCanvas } from './canvas.jsx';
import { toEditor, toProject, projectScreens, scopedScreen } from './model.mjs';
import { EngineeringSettings, engineeringCatalog } from './engineering.jsx';
import { RecipeTransferSettings } from './recipe-transfer-settings.jsx';
import { ProjectHistory, MergeReview, exportCandidate } from './project-history.jsx';
import { readCandidate, retainCandidate, editorIdentity, recoveryPrefix } from './recovery-cache.mjs';
import { WorkspacePage } from './workspace.jsx';
import { api, json } from './api.mjs';
import { Localization, useUi } from './localization.jsx';
import { IdentitySettings } from './identity-settings.jsx';
import { ProjectSettings, getSettings } from './project-settings.jsx';
import { AlarmConsole } from './alarm-console.jsx';
import { RecipeWorkspace } from './recipes.jsx';
import { SecurityContext, SecurityBar, SecurityAdmin, allowed } from './security.jsx';
import { Popup } from './touch-entry.jsx';

const editorOverrides = { headerActions: () => null };

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isAlarmSnapshot(alarms) {
  if (!isRecord(alarms)) return false;
  const { states, outstanding, annunciated_outstanding: annunciated = outstanding,
    active_count, unacknowledged_count, annunciated_active_count = active_count,
    annunciated_unacknowledged_count = unacknowledged_count, shelved_count = 0,
    sampled_revision = null, evaluation_stale = false } = alarms;
  const counts = [active_count, unacknowledged_count, annunciated_active_count,
    annunciated_unacknowledged_count, shelved_count];
  return counts.every(count => Number.isSafeInteger(count) && count >= 0)
    && (sampled_revision === null || Number.isSafeInteger(sampled_revision))
    && typeof evaluation_stale === 'boolean'
    && isRecord(states) && Object.values(states).every(state => ['good', 'bad'].includes(state?.quality))
    && Array.isArray(outstanding) && Array.isArray(annunciated)
    && annunciated.every(alarm => isRecord(alarm) && [1, 2, 3, 4].includes(alarm.priority)
      && typeof alarm.message === 'string'
      && (alarm.occurrence_id === undefined || Number.isSafeInteger(alarm.occurrence_id))
      && (alarm.messages === undefined || (isRecord(alarm.messages)
        && Object.values(alarm.messages).every(message => typeof message === 'string'))));
}

function ScreenView({ screen, config }) {
  const data = toEditor(screen);
  return <ScreenControls.Provider value={screen.controls}>
    {screen.layout ? <ScreenFrame {...data.root.props} canvas={<CanvasSurface data={data} config={config} />} />
      : <Render config={config} data={data} />}
  </ScreenControls.Provider>;
}

function ScreenPopup({ screen, config, opener, close }) {
  const ui = useUi();
  return <Popup title={screen.title} close={close} closeLabel={ui('closePopup')} opener={opener}>
    <ScreenView screen={screen} config={config} />
  </Popup>;
}

function Builder({ initial, catalog }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext);
  const canEdit = allowed(session, 'project.edit');
  const [editorId] = useState(editorIdentity);
  const recoveryKey = useRef(recoveryPrefix(initial.project_id, session?.user) + editorId).current;
  const [cached] = useState(() => readCandidate(recoveryKey));
  const starting = cached?.local || initial.draft;
  const base = useRef(cached?.base || initial.draft);
  const [recovery, setRecovery] = useState(cached);
  const [applyReason, setApplyReason] = useState('');
  const [scope, setScope] = useState('overview');
  const [previewRoot, setPreviewRoot] = useState('');
  const scopeRef = useRef('overview');
  const document = useRef(starting);
  const [initialData, setInitialData] = useState(toEditor(starting));
  const [canvasData, setCanvasData] = useState(initialData);
  const [canvasClipboard, setCanvasClipboard] = useState(null);
  const revision = useRef(cached?.base_revision || initial.draft_revision);
  const latest = useRef(toEditor(starting));
  const [generation, setGeneration] = useState(0);
  const chain = useRef(Promise.resolve(true));
  const timer = useRef();
  const blocked = useRef(!!cached);
  const [message, setMessage] = useState(`Draft ${initial.draft_revision} saved. Live values are visible while editing.`);
  const [busy, setBusy] = useState(false);
  const [previewControls, setPreviewControls] = useState(starting.controls);
  const metadata = useRef(getSettings(starting));
  const [settings, setSettings] = useState(metadata.current);
  const [tab, setTab] = useState('screen');
  const [previewProject, setPreviewProject] = useState({ ...starting, ...metadata.current });
  const template = settings.faceplates.find(item => `faceplate:${item.id}` === scope);
  const dynamicCatalog = useMemo(() => engineeringCatalog(catalog, settings, template), [catalog, settings, template]);
  const config = useMemo(() => createConfig(dynamicCatalog), [dynamicCatalog]);
  useEffect(() => { window.dispatchEvent(new CustomEvent('openhmi-editor-scope', { detail: { screen: scope.startsWith('faceplate:') ? 'overview' : scope, root: scope.startsWith('faceplate:') ? previewRoot : '' } })); }, [scope, previewRoot]);
  const previewValues = { ...live.values }, previewSamples = { ...live.samples };
  if (template && previewRoot) for (const member of Object.keys(template.members)) {
    const source = previewRoot + '.' + member;
    if (Object.hasOwn(live.values, source)) previewValues['$.' + member] = live.values[source];
    previewSamples['$.' + member] = live.samples?.[source];
  }

  function compose(data, projectSettings = metadata.current) {
    const content = toProject(data);
    const next = { ...document.current, ...projectSettings };
    if (scopeRef.current === 'overview') Object.assign(next, { title: content.title, columns: content.columns, layout: content.layout, controls: content.controls });
    else if (scopeRef.current.startsWith('faceplate:')) next.faceplates = next.faceplates.map(item => `faceplate:${item.id}` === scopeRef.current ? { ...item, name: content.title, controls: content.controls } : item);
    else next.screens = next.screens.map(item => item.id === scopeRef.current ? { ...item, title: content.title, columns: content.columns, layout: content.layout, controls: content.controls } : item);
    return next;
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  function recoveryCandidate() { return { project_id: initial.project_id, base: base.current, local: compose(latest.current), base_revision: revision.current }; }
  function cache() {
    try { retainCandidate(recoveryKey, recoveryCandidate(), blocked.current); }
    catch { setMessage('Browser recovery storage is unavailable. Export your local recovery JSON before closing this editor.'); }
  }
  function accepted(state) {
    clearTimeout(timer.current);
    base.current = state.draft; document.current = state.draft; revision.current = state.draft_revision;
    metadata.current = getSettings(state.draft); latest.current = toEditor(state.draft);
    scopeRef.current = 'overview'; setScope('overview'); setSettings(metadata.current); setInitialData(latest.current); setCanvasData(latest.current);
    setPreviewControls(state.draft.controls); setPreviewProject(state.draft); setGeneration(value => value + 1);
    blocked.current = false; setRecovery(null); setTab('screen');
    try { localStorage.removeItem(recoveryKey); } catch {}
    setMessage(`Merged draft ${state.draft_revision} saved. Review and Apply live separately.`);
  }

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
        base.current = state.draft;
        cache();
        setMessage(`Draft ${state.draft_revision} saved. Apply live to update runtime viewers.`);
        return true;
      } catch (error) {
        if (error.conflict) { blocked.current = true; clearTimeout(timer.current); cache(); setRecovery(recoveryCandidate()); }
        else cache();
        setMessage(`Not saved: ${error.message}${error.conflict ? ' Your changes remain in this editor; copy them before reloading.' : ''}`);
        return false;
      }
    });
    return chain.current;
  }

  function changed(data) {
    if (recovery) return;
    latest.current = data;
    setCanvasData(data);
    setPreviewControls(toProject(data).controls);
    const next = compose(data);
    setPreviewProject(next);
    metadata.current = getSettings(next);
    cache();
    clearTimeout(timer.current);
    if (blocked.current) return;
    setMessage('Draft changed. Saving...');
    timer.current = setTimeout(() => save(data), 600);
  }

  function settingsChanged(next) {
    if (recovery) return;
    metadata.current = next;
    setSettings(next);
    setPreviewProject(compose(latest.current, next));
    cache();
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
    latest.current = data; setInitialData(data); setCanvasData(data); setPreviewControls(target.controls); setTab('screen');
    setSettings(getSettings(document.current));
  }

  function changeLayout(freeform) {
    if (!freeform && !window.confirm('Switch to grid layout and discard freeform positions and containers?')) return;
    const current = latest.current;
    const next = { ...current, root: { props: { ...current.root.props, layout: freeform ? initialCanvas(current) : null } } };
    setInitialData(next);
    setGeneration(value => value + 1);
    changed(next);
  }

  async function apply() {
    clearTimeout(timer.current);
    setBusy(true);
    const candidate = latest.current;
    try {
      if (!await save(candidate)) return;
      const state = await api('/api/project/apply', json('POST', { expected_revision: revision.current, reason: applyReason.trim() || 'Live apply' }));
      setMessage(`Applied live revision ${state.active_revision}. Existing viewers update automatically.`);
    } catch (error) {
      if (error.conflict) { blocked.current = true; cache(); setRecovery(recoveryCandidate()); }
      setMessage(`Not applied: ${error.message}`);
    } finally { setBusy(false); }
  }

  return <Localization project={previewProject}><Live.Provider value={{ ...live, values: previewValues, samples: previewSamples, previewRoot: template ? previewRoot : '', project: previewProject }}><ScreenControls.Provider value={previewControls}>
    <div className="builder-guide"><p>Drop a control, select a tag, and apply your screen. No code required.</p>
      <div><button disabled={!canEdit} onClick={() => { clearTimeout(timer.current); save(latest.current); }}>Save draft</button>
        <button className="apply-button" onClick={apply} disabled={busy || !canEdit}>{busy ? 'Applying...' : 'Apply live'}</button>
        <a href="/runtime" target="_blank" rel="noreferrer">Open live screen ↗</a><a href="/projects">Projects</a><a href="/revisions">Revisions</a><span>Editing: {scope}</span>
        {!template && tab === 'screen' && <button type="button" disabled={!canEdit || !!recovery}
          onClick={() => changeLayout(!canvasData.root.props.layout)}>
          {canvasData.root.props.layout ? 'Switch to grid layout' : 'Enable freeform layout'}
        </button>}</div>
      <label>Apply reason<input aria-label="Apply reason" value={applyReason} maxLength={1000} onChange={event => setApplyReason(event.target.value)} placeholder="Optional description of this live change" /></label></div>
    <p role="status" aria-label="Draft status" className="save-status">{message}</p>
    <div className="operations-actions"><button disabled={!canEdit} onClick={() => { clearTimeout(timer.current); blocked.current = true; cache(); setRecovery(recoveryCandidate()); }}>Review local recovery / merge</button><button onClick={() => exportCandidate(recoveryCandidate())}>Export local recovery JSON</button></div>
    {template && <label className="builder-guide">Faceplate preview UDT<select value={previewRoot} onChange={event => setPreviewRoot(event.target.value)}><option value="">Choose live UDT instance</option>{settings.tags.filter(tag => tag.type === 'struct' && (!template.udt_type || template.udt_type === tag.udt_type)).map(tag => <option key={tag.name}>{tag.name}</option>)}</select></label>}
    <nav className="project-tabs" aria-label="Project tools">{[['screen', 'Screen'], ['screens', 'Screens'], ['connections', 'Connections'], ['tags', 'Tags'], ['faceplates', 'Faceplates'], ['history', 'History'], ['commands', 'Commands'], ['recipe_transfers', 'PLC recipes'], ['languages', 'Languages'], ['alarms', 'Alarm setup'], ['identity', 'PLC login']].map(([key, label]) =>
      <button key={key} aria-pressed={tab === key} onClick={() => { clearTimeout(timer.current); save(latest.current); setSettings(metadata.current); setTab(key); }}>{label}</button>)}<a href="/recipe-editor">Recipes</a></nav>
    {tab === 'identity' && <IdentitySettings settings={settings} onChange={settingsChanged} catalog={dynamicCatalog} />}
    {['languages', 'alarms'].includes(tab) && <ProjectSettings tab={tab} settings={settings} controls={previewControls} title={previewProject.title} catalog={dynamicCatalog} onChange={settingsChanged} />}
    {tab === 'recipe_transfers' && <RecipeTransferSettings settings={settings} onChange={settingsChanged} />}
    {['screens', 'connections', 'tags', 'faceplates', 'history', 'commands'].includes(tab) && <EngineeringSettings key={tab} tab={tab} settings={settings} onChange={settingsChanged} editScope={editScope} catalog={dynamicCatalog} projectInstance={initial.project_instance} />}
    <div hidden={tab !== 'screen'}>
      {canvasData.root.props.layout
        ? <CanvasEditor key={`${scope}:${generation}`} data={canvasData} config={config} onChange={changed}
          canEdit={canEdit && !recovery} clipboard={canvasClipboard} onCopy={setCanvasClipboard} />
        : <Puck key={`${scope}:${generation}`} config={config} data={initialData} iframe={{ enabled: false }}
          headerTitle="Screen builder" headerPath="" height="calc(100vh - 182px)" onChange={changed} overrides={editorOverrides} />}
    </div>
    {recovery && <MergeReview candidate={recovery} onClose={() => { setRecovery(null); setMessage('Local changes retained. Review and merge before saving to the server.'); }} onAccepted={accepted} />}
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
  const screenNavigation = useRef(null);
  const clientId = useRef(crypto.randomUUID());
  const subscriptionSequence = useRef(0);
  const screens = useMemo(() => projectScreens(active.project), [active.project]);
  const invalidScreen = location.pathname === '/runtime' && !screens.some(screen => screen.id === screenId && !screen.popup);
  const currentScreen = scopedScreen(active.project, invalidScreen ? 'overview' : screenId);
  const invalidPopup = invalidScreen && popups.length ? 0
    : popups.findIndex(({ id }) => !screens.some(screen => screen.id === id && screen.popup));
  const visiblePopups = invalidPopup < 0 ? popups : popups.slice(0, invalidPopup);
  useLayoutEffect(() => {
    if (!invalidScreen && invalidPopup < 0) return;
    if (invalidScreen) {
      setScreenId('overview');
      const url = new URL(location.href);
      url.searchParams.delete('screen');
      history.replaceState(history.state, '', url);
    }
    if (invalidPopup >= 0) setPopups(visiblePopups);
    if (document.activeElement === document.body) {
      const opener = invalidScreen ? null : popups[invalidPopup].opener;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
      if (document.activeElement === document.body) {
        const modal = Array.from(document.querySelectorAll('dialog.hmi-popup:modal')).at(-1);
        const fallback = modal?.querySelector('header button')
          ?? screenNavigation.current?.querySelector('[aria-pressed="true"]');
        fallback?.focus({ preventScroll: true });
      }
    }
  }, [invalidScreen, invalidPopup, popups, visiblePopups]);
  const runtimeCatalog = useMemo(() => engineeringCatalog(catalog, getSettings(active.project)), [catalog, active.project]);
  const config = useMemo(() => createConfig(runtimeCatalog), [runtimeCatalog]);
  const updateRate = useRef(500);
  updateRate.current = runtime ? Math.min(currentScreen.update_ms || 500, ...visiblePopups.map(({ id }) => screens.find(item => item.id === id)?.update_ms || 500)) : 500;
  const [screenConnected, setScreenConnected] = useState(true);
  const [session, setSession] = useState(null);
  const [identityAvailable, setIdentityAvailable] = useState(true);
  const editorStarted = useRef(false);
  if (allowed(session, 'project.edit')) editorStarted.current = true;
  async function refreshSession() { try { setSession(await api('/api/security/session')); } catch { setSession(null); } }
  useEffect(() => {
    function navigate(event) {
      const { mode, screen, opener } = event.detail;
      if (mode === 'navigate') { setScreenId(screen); setPopups([]); history.replaceState(null, '', `/runtime?screen=${encodeURIComponent(screen)}`); }
      if (mode === 'popup') setPopups(previous => previous.some(item => item.id === screen)
        ? previous : [...previous, { id: screen, opener }].slice(-5));
      if (mode === 'close_popup') setPopups(previous => previous.slice(0, -1));
    }
    window.addEventListener('openhmi-navigate', navigate);
    const editor = event => setEditorSubscription(event.detail);
    window.addEventListener('openhmi-editor-scope', editor);
    return () => { window.removeEventListener('openhmi-navigate', navigate); window.removeEventListener('openhmi-editor-scope', editor); };
  }, []);
  const leasedScreens = runtime ? location.pathname === '/runtime' ? [currentScreen.id, ...visiblePopups.map(({ id }) => id)].join(',') : '' : editorSubscription.screen;
  useEffect(() => {
    const screens = leasedScreens ? leasedScreens.split(',') : [];
    const previewRoot = runtime ? '' : editorSubscription.root;
    let generation = 0, timer;
    function subscribe(nextScreens, nextPreview, keepalive = false) {
      return api('/api/subscriptions', {
        ...json('POST', {
          client: clientId.current, screens: nextScreens, preview_root: nextPreview,
          sequence: ++subscriptionSequence.current,
        }),
        keepalive,
      });
    }
    async function heartbeat() {
      const currentGeneration = generation;
      try { await subscribe(screens, previewRoot); } catch {}
      if (generation === currentGeneration) timer = setTimeout(heartbeat, 5000);
    }
    function stopHeartbeat() {
      generation++;
      clearTimeout(timer);
    }
    function release() {
      stopHeartbeat();
      if (screens.length || previewRoot) subscribe([], '', true).catch(() => {});
    }
    function restore(event) {
      if (event.persisted) heartbeat();
    }
    window.addEventListener('pagehide', release);
    window.addEventListener('pageshow', restore);
    heartbeat();
    return () => {
      stopHeartbeat();
      window.removeEventListener('pagehide', release);
      window.removeEventListener('pageshow', restore);
    };
  }, [leasedScreens, editorSubscription.root, runtime]);
  useEffect(() => {
    function poll(path, onSuccess, onFailure) {
      let stopped = false, timer;
      async function tick() {
        try {
          const data = await api(path);
          if (!stopped) onSuccess(data);
        } catch {
          if (!stopped) onFailure();
        }
        if (!stopped) timer = setTimeout(tick, updateRate.current);
      }
      tick();
      return () => { stopped = true; clearTimeout(timer); };
    }

    const stopTags = poll('/api/tags', tags => {
      const { values, samples = {}, connections = [], plc_hold: plcHold = false } = tags ?? {};
      if (!isRecord(values) || !isRecord(samples) || typeof plcHold !== 'boolean'
        || !Array.isArray(connections) || connections.some(route =>
          typeof route?.id !== 'string' || typeof route.connected !== 'boolean')) {
        throw new Error('Invalid tag status response');
      }
      setLive(previous => ({ ...previous, values, samples, connections, plcHold, connected: true }));
    }, () => {
      setLive(previous => ({ ...previous, values: {}, samples: {}, connected: false, connections: [], plcHold: false }));
    });
    const stopAlarms = poll('/api/alarms', alarms => {
      if (!isAlarmSnapshot(alarms)) throw new Error('Invalid alarm status response');
      setLive(previous => ({ ...previous, alarms, alarmConnected: true }));
    }, () => {
      setLive(previous => ({ ...previous, alarmConnected: false }));
    });
    const stopRecipe = poll('/api/recipes/selected', recipeSelection => {
      setLive(previous => ({ ...previous, recipeSelection, recipeConnected: true }));
    }, () => {
      setLive(previous => ({ ...previous, recipeSelection: null, recipeConnected: false }));
    });
    const stopIdentity = poll('/api/security/session', identity => {
      setSession(identity);
      setIdentityAvailable(true);
    }, () => setIdentityAvailable(false));
    const stopProject = poll('/api/project/active', next => {
      if (next.project_instance && next.project_instance !== initial.project_instance) {
        if (runtime) { location.replace(location.pathname === '/projects' ? '/' : location.href); return; }
        setProjectChanged(true);
      }
      setActive(previous => previous.revision === next.revision ? previous : next);
      setScreenConnected(true);
    }, () => setScreenConnected(false));
    return () => { stopTags(); stopAlarms(); stopRecipe(); stopIdentity(); stopProject(); };
  }, [runtime]);
  const plcConfigured = active.project.connections?.some(connection => connection.enabled);
  const station = <SecurityContext.Provider value={{ session, refreshSession }}><Live.Provider value={{ ...live, project: active.project, activeRevision: active.revision }}>
    <header className="app-header"><a className="brand" href="/">OpenHMI</a><span>Build it visually. Extend it with Python.</span>
      <ConnectionStatus details /></header>
    <SecurityBar session={session} refresh={refreshSession} plcConfigured={plcConfigured} />
    {!identityAvailable && <p role="status" className="save-status">HMI identity status unavailable. Showing the last confirmed sign-in; the server checks permission on every operation.</p>}
    {projectChanged && <p role="alert" className="save-status">A different project was opened. Saves from this editor are blocked; copy any unsaved work before reloading. <button onClick={() => location.reload()}>Reload opened project</button></p>}
    {live.plcHold && <p role="status" className="save-status">PLC connections are held. Review the project and use Apply live to enable its configured connections.</p>}
    {runtime ? <main className={currentScreen.layout && location.pathname === '/runtime' ? 'runtime canvas-runtime' : 'runtime'}><div className="runtime-bar"><span>Live screen / revision {active.revision}</span>
      <a href="/runtime">Overview</a><a href="/alarms">Alarms</a><a href="/recipes">Recipes</a><a href="/commands">Commands</a><a href="/activity">Activity</a><a href="/diagnostics">Diagnostics</a><a href="/revisions">Revisions</a><a href="/projects">Projects</a><a href="/">Edit screen</a></div>{!screenConnected && <p role="alert">Screen updates unavailable. Showing the last applied layout.</p>}
      {location.pathname === '/revisions' ? <ProjectHistory /> : location.pathname === '/commands' ? <CommandConsole /> : location.pathname === '/activity' ? <ActivityConsole /> : location.pathname === '/diagnostics' ? <DiagnosticsConsole /> : location.pathname === '/projects' ? <WorkspacePage key={session?.user?.name || 'anonymous'} /> : location.pathname === '/security' ? <SecurityAdmin /> : ['/recipes', '/recipe-editor'].includes(location.pathname) ? <RecipeWorkspace edit={location.pathname === '/recipe-editor'} catalog={runtimeCatalog} /> : location.pathname === '/alarms' ? <AlarmConsole /> : <>
        <nav ref={screenNavigation} className="screen-navigation" aria-label="HMI screens">{screens.filter(screen => !screen.popup).map(screen => <button key={screen.id} aria-pressed={currentScreen.id === screen.id} onClick={() => { setScreenId(screen.id); history.replaceState(null, '', `/runtime?screen=${encodeURIComponent(screen.id)}`); }}>{screen.title}</button>)}</nav>
        <ScreenView screen={currentScreen} config={config} />
        {visiblePopups.map(({ id, opener }) => <ScreenPopup key={id} screen={scopedScreen(active.project, id)} config={config}
          opener={opener} close={() => setPopups(previous => previous.filter(item => item.id !== id))} />)}
      </>}</main> : editorStarted.current ? <MemoBuilder initial={initial} catalog={catalog} /> : <main className="security-admin"><p>Sign in with a group that has project.edit permission to edit this HMI.</p><a href="/runtime">Open live screen</a></main>}
  </Live.Provider></SecurityContext.Provider>;
  return runtime ? <Localization project={active.project}>{station}</Localization> : station;
}

try {
  const [initial, catalog] = await Promise.all([api('/api/project'), api('/api/catalog')]);
  createRoot(document.getElementById('root')).render(<App initial={initial} catalog={catalog} />);
} catch (error) {
  document.getElementById('root').textContent = `Unable to open project: ${error.message}. Refresh to retry.`;
}
