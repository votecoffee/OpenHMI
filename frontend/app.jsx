import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Puck, Render } from '@puckeditor/core';
import '@puckeditor/core/no-external.css';
import '../openhmi/web/style.css';

const Live = createContext({ values: {}, connected: false });
const types = { numeric: 'NumericDisplay', indicator: 'Indicator', button: 'ActionButton' };
const kinds = Object.fromEntries(Object.entries(types).map(([kind, type]) => [type, kind]));
const editorOverrides = { headerActions: () => null };

function toEditor(project) {
  return {
    root: { props: { title: project.title, columns: project.columns } },
    content: project.controls.map(({ kind, ...props }) => ({ type: types[kind], props })),
  };
}

function toProject(data) {
  return {
    schema_version: 1, title: data.root.props.title, columns: Number(data.root.props.columns),
    controls: data.content.map(({ type, props }) => {
      const base = { kind: kinds[type], id: props.id, label: props.label };
      if (type === 'ActionButton') return { ...base, action: props.action };
      if (type === 'Indicator') return { ...base, tag: props.tag };
      return { ...base, tag: props.tag, unit: props.unit, decimals: Number(props.decimals) };
    }),
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, { signal: AbortSignal.timeout(5000), ...options });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => `${item.loc.join('.')}: ${item.msg}`).join('; ') : data.detail;
    const error = new Error(detail || `HTTP ${response.status}`);
    error.conflict = response.status === 409;
    throw error;
  }
  return data;
}

function json(method, body) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

function NumericDisplay({ label, tag, unit, decimals }) {
  const live = useContext(Live);
  const value = live.values[tag];
  const valid = live.connected && typeof value === 'number';
  return <article className="hmi-card" data-control="numeric">
    <span className="hmi-label">{label}</span>
    <strong className="hmi-value">{valid ? value.toFixed(decimals) : 'Unavailable'} <small>{valid && unit}</small></strong>
    <span className="hmi-source">{tag}</span>
  </article>;
}

function Indicator({ label, tag }) {
  const live = useContext(Live);
  const value = live.values[tag];
  const valid = live.connected && typeof value === 'boolean';
  return <article className="hmi-card" data-control="indicator">
    <span className="hmi-label">{label}</span>
    <strong className={`hmi-state ${valid && value ? 'is-on' : ''}`}>
      {valid ? (value ? 'ON' : 'OFF') : 'Unavailable'}
    </strong><span className="hmi-source">{tag}</span>
  </article>;
}

function ActionButton({ label, action, puck }) {
  const live = useContext(Live);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  async function invoke() {
    setBusy(true);
    try {
      await api(`/api/actions/${encodeURIComponent(action)}`, json('POST', {}));
      setFeedback('Action completed');
    } catch (error) { setFeedback(error.message); }
    finally { setBusy(false); }
  }
  return <article className="hmi-card" data-control="button">
    <span className="hmi-label">{label}</span>
    <button className="hmi-action" disabled={puck?.isEditing || !live.connected || busy} onClick={invoke}>
      {busy ? 'Working...' : label}
    </button><span className="hmi-source">{puck?.isEditing ? 'Select to configure action' : feedback || 'Python action'}</span>
  </article>;
}

function createConfig(catalog) {
  const tagField = type => ({ type: 'select', label: 'Tag', options: catalog.tags
    .filter(tag => tag.type === type).map(tag => ({ label: tag.name, value: tag.name })) });
  const labelField = { type: 'text', label: 'Label' };
  return {
    root: {
      fields: {
        title: { type: 'text', label: 'Screen name' },
        columns: { type: 'select', label: 'Columns', options: [1, 2, 3].map(value => ({ label: String(value), value })) },
      },
      defaultProps: { title: 'My live HMI', columns: 2 },
      render: ({ children, title, columns }) => <section className="hmi-screen">
        <div className="hmi-screen-heading"><span className="eyebrow">LIVE HMI / SIMULATION</span><h1>{title}</h1></div>
        <div className="hmi-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>{children}</div>
      </section>,
    },
    categories: { hmi: { title: 'HMI controls', components: Object.values(types) } },
    components: {
      NumericDisplay: {
        label: 'Numeric display',
        fields: { label: labelField, tag: tagField('number'), unit: { type: 'text', label: 'Units' },
          decimals: { type: 'select', label: 'Decimal places', options: [0, 1, 2, 3, 4].map(value => ({ label: String(value), value })) } },
        defaultProps: { label: 'Tank level', tag: 'TankLevel', unit: '%', decimals: 1 },
        render: NumericDisplay,
      },
      Indicator: {
        label: 'Indicator', fields: { label: labelField, tag: tagField('boolean') },
        defaultProps: { label: 'Motor', tag: 'MotorRunning' }, render: Indicator,
      },
      ActionButton: {
        label: 'Action button', fields: { label: labelField, action: { type: 'select', label: 'Action',
          options: catalog.actions.map(action => ({ label: action.label, value: action.name })) } },
        defaultProps: { label: 'Toggle simulated motor', action: 'toggle_motor' }, render: ActionButton,
      },
    },
  };
}

function Builder({ initial, config }) {
  const initialData = useMemo(() => toEditor(initial.draft), [initial.draft]);
  const revision = useRef(initial.draft_revision);
  const latest = useRef(toEditor(initial.draft));
  const chain = useRef(Promise.resolve(true));
  const timer = useRef();
  const blocked = useRef(false);
  const [message, setMessage] = useState(`Draft ${initial.draft_revision} saved. Live values are visible while editing.`);
  const [busy, setBusy] = useState(false);

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

  return <>
    <div className="builder-guide"><p>Drop a control, select a tag, and apply your screen. No code required.</p>
      <div><button onClick={() => { clearTimeout(timer.current); save(latest.current); }}>Save draft</button>
        <button className="apply-button" onClick={apply} disabled={busy}>{busy ? 'Applying...' : 'Apply live'}</button>
        <a href="/runtime" target="_blank" rel="noreferrer">Open live screen ↗</a></div></div>
    <p role="status" aria-label="Draft status" className="save-status">{message}</p>
    <Puck config={config} data={initialData} iframe={{ enabled: false }}
      headerTitle="Screen builder" headerPath="" height="calc(100vh - 182px)" onChange={changed}
      overrides={editorOverrides} />
  </>;
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
      <Render config={config} data={toEditor(active.project)} /></main> : <MemoBuilder initial={initial} config={config} />}
  </Live.Provider>;
}

try {
  const [initial, catalog] = await Promise.all([api('/api/project'), api('/api/catalog')]);
  createRoot(document.getElementById('root')).render(<App initial={initial} catalog={catalog} />);
} catch (error) {
  document.getElementById('root').textContent = `Unable to open project: ${error.message}. Refresh to retry.`;
}
