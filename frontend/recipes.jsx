import React, { useContext, useEffect, useState } from 'react';
import { api, json } from './api.mjs';
import { Live } from './controls.jsx';
import { useLocalization } from './localization.jsx';
import { SecurityContext } from './security.jsx';
import { RecipeTransferPanel } from './recipe-transfers.jsx';

const blank = () => ({ title: '', description: '', image_id: null, parameters: [] });
const clone = value => JSON.parse(JSON.stringify(value));

export function RecipePicture({ content }) {
  const { ui } = useLocalization();
  return content?.image_id ? <img className="recipe-image" src={`/api/recipe-images/${content.image_id}`} alt={content.title} />
    : <div className="recipe-no-image">{ui('recipeNoImage')}</div>;
}

export function LoadedRecipe({ compact = false }) {
  const live = useContext(Live);
  const { ui } = useLocalization();
  const selected = live.recipeSelection?.snapshot;
  if (!live.recipeConnected) return <p className="hmi-quality">{ui('recipeUnavailable')}</p>;
  if (!selected) return <p>{ui('recipeNotLoaded')}</p>;
  return <div className={`loaded-recipe ${compact ? 'compact' : ''}`}>
    <RecipePicture content={selected.content} />
    <div><strong>{selected.content.title}</strong><p>{selected.code} / {ui('recipeRevision')} {selected.number}</p>
      <p className="recipe-production">{selected.production_approved ? ui('recipeProduction') : ui('recipeTest')}</p>
      {!compact && <><p>{ui('recipeLoadedBy')}: {selected.loaded_by} · {selected.loaded_at}</p>
        {selected.approved_by && <p>{ui('recipeApprovedBy')}: {selected.approved_by}</p>}
        <ParameterValues content={selected.content} /></>}
    </div>
  </div>;
}

function ParameterValues({ content }) {
  const { ui } = useLocalization();
  return <table className="recipe-values"><thead><tr><th>{ui('recipeParameter')}</th><th>{ui('recipeValue')}</th><th>{ui('recipeUnits')}</th></tr></thead>
    <tbody>{content.parameters.map(parameter => <tr key={parameter.name}><td>{parameter.label}</td>
      <td>{typeof parameter.value === 'boolean' ? ui(parameter.value ? 'on' : 'off') : String(parameter.value)}</td><td>{parameter.unit}</td></tr>)}</tbody></table>;
}

function RecipeSession({ session, onChange }) {
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function signIn(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await api('/api/recipe-auth/login', json('POST', { name, password }));
      setPassword(''); onChange({ ...session, user: result.user });
    } catch (problem) { setError(problem.message); }
    finally { setBusy(false); }
  }
  return <div className="recipe-session">
    {session.user ? <><span>Signed in: <strong>{session.user.name}</strong> ({session.user.roles.join(', ')})</span>
      <button onClick={async () => { try { await api('/api/recipe-auth/logout', json('POST', {})); onChange({ ...session, user: null }); } catch (problem) { setError(problem.message); } }}>Sign out</button></>
      : session.configured ? <form onSubmit={signIn}><label>Recipe user<input autoComplete="username" value={name} onChange={event => setName(event.target.value)} /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></label>
        <button disabled={busy}>Sign in</button></form>
      : <p>Recipe accounts are not configured. An administrator can create them with openhmi-users and restart OpenHMI.</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}

function ParameterEditor({ content, update, disabled }) {
  function change(index, patch) { update({ ...content, parameters: content.parameters.map((parameter, i) => i === index ? { ...parameter, ...patch } : parameter) }); }
  return <fieldset disabled={disabled}><legend>Recipe parameters</legend>
    <table className="parameter-editor"><thead><tr><th>Name</th><th>Label</th><th>Type</th><th>Value</th><th>Units</th><th>Minimum</th><th>Maximum</th><th /></tr></thead>
      <tbody>{content.parameters.map((parameter, index) => <tr key={index} data-parameter-row>
        <td><input aria-label={`Parameter ${index + 1} name`} value={parameter.name} onChange={event => change(index, { name: event.target.value })} /></td>
        <td><input aria-label={`Parameter ${index + 1} label`} value={parameter.label} onChange={event => change(index, { label: event.target.value })} /></td>
        <td><select aria-label={`Parameter ${index + 1} type`} value={parameter.type} onChange={event => change(index, { type: event.target.value,
          value: event.target.value === 'boolean' ? false : event.target.value === 'text' ? '' : 0, minimum: null, maximum: null })}>
          {['number', 'integer', 'boolean', 'text'].map(type => <option key={type}>{type}</option>)}</select></td>
        <td>{parameter.type === 'boolean' ? <input aria-label={`Parameter ${index + 1} value`} type="checkbox" checked={parameter.value} onChange={event => change(index, { value: event.target.checked })} />
          : <input aria-label={`Parameter ${index + 1} value`} value={parameter.value} onChange={event => change(index, { value: event.target.value })} />}</td>
        <td><input aria-label={`Parameter ${index + 1} units`} value={parameter.unit} onChange={event => change(index, { unit: event.target.value })} /></td>
        <td><input aria-label={`Parameter ${index + 1} minimum`} disabled={!['number', 'integer'].includes(parameter.type)} value={parameter.minimum ?? ''} onChange={event => change(index, { minimum: event.target.value })} /></td>
        <td><input aria-label={`Parameter ${index + 1} maximum`} disabled={!['number', 'integer'].includes(parameter.type)} value={parameter.maximum ?? ''} onChange={event => change(index, { maximum: event.target.value })} /></td>
        <td><button onClick={() => update({ ...content, parameters: content.parameters.filter((_, i) => i !== index) })}>Remove {index + 1}</button></td>
      </tr>)}</tbody></table>
    <button onClick={() => {
      let next = content.parameters.length + 1;
      while (content.parameters.some(parameter => parameter.name === `parameter_${next}`)) ++next;
      update({ ...content, parameters: [...content.parameters, { name: `parameter_${next}`, label: `Parameter ${next}`, type: 'number', value: 0, unit: '', minimum: null, maximum: null }] });
    }}>Add parameter</button>
  </fieldset>;
}

function validatedContent(content) {
  return { ...content, parameters: content.parameters.map(parameter => {
    const numeric = ['number', 'integer'].includes(parameter.type);
    if (numeric && !String(parameter.value).trim()) throw new Error(`Enter a value for ${parameter.label}`);
    return { ...parameter, value: numeric ? Number(parameter.value) : parameter.value,
      minimum: parameter.minimum == null || parameter.minimum === '' ? null : Number(parameter.minimum),
      maximum: parameter.maximum == null || parameter.maximum === '' ? null : Number(parameter.maximum) };
  }) };
}

export function RecipeWorkspace({ edit, catalog }) {
  const live = useContext(Live);
  const hmiSecurity = useContext(SecurityContext);
  const { ui } = useLocalization();
  const [state, setState] = useState(null);
  const [session, setSession] = useState({ configured: false, user: null });
  const [source, setSource] = useState(null);
  const [content, setContent] = useState(blank);
  const [code, setCode] = useState('');
  const [reason, setReason] = useState('');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [policy, setPolicy] = useState(null);
  useEffect(() => { if (hmiSecurity?.session?.configured) setSession(hmiSecurity.session); }, [hmiSecurity?.session]);
  function choose(revision) {
    setSource(revision); setContent(revision ? clone(revision.content) : blank()); setCode(revision?.code || ''); setReason(''); setDirty(false);
  }
  async function refresh(initial = false) {
    const [next, identity] = await Promise.all([api('/api/recipes'), api('/api/recipe-auth/session')]);
    setState(next); setSession(identity);
    if (initial) { choose(next.revisions[0] || null); setPolicy(next.change_policy.policy); }
    return next;
  }
  useEffect(() => { refresh(true).catch(error => setMessage(error.message)); }, []);
  const can = role => !!session.user && (session.user.roles.includes(role) || session.user.roles.includes('administrator'));
  const editable = can('engineer') && !!state?.gates.editing.allowed && source?.status !== 'in_review';
  function update(next) { setContent(next); setDirty(true); }
  async function perform(operation, acceptRevision = false) {
    setBusy(true);
    try {
      if (!reason.trim()) throw new Error('Enter a change, review or load reason');
      const result = await operation();
      const next = await refresh();
      if (acceptRevision) choose(result);
      else if (source) setSource(next.revisions.find(revision => revision.id === source.id) || source);
      setReason(''); setMessage('Recipe operation recorded.');
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function save() {
    await perform(() => {
      const payload = validatedContent(content);
      if (!source) return api('/api/recipes', json('POST', { code, content: payload, reason }));
      const latest = state.revisions.find(revision => revision.recipe_id === source.recipe_id);
      return api(`/api/recipes/${source.recipe_id}/revisions`, json('POST', { expected_latest_revision: latest.id, parent_revision: source.id, content: payload, reason }));
    }, true);
  }
  function transition(action) { return perform(() => api(`/api/recipe-revisions/${source.id}/transition`, json('POST', { action, expected_version: source.version, reason })), true); }
  async function load(clear = false) {
    await perform(() => api('/api/recipes/select', json('POST', { revision_id: clear ? null : source.id, expected_revision_version: clear ? null : source.version,
      expected_selection_version: live.recipeSelection?.version || state.selection.version, reason })));
  }
  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      if (!reason.trim()) throw new Error('Enter an image change reason first');
      const result = await api(`/api/recipe-images?reason=${encodeURIComponent(reason)}`, { method: 'POST', headers: { 'Content-Type': file.type }, body: file });
      update({ ...content, image_id: result.image_id }); setMessage('Image uploaded. Save a draft to attach it to the recipe revision.');
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); event.target.value = ''; }
  }
  if (!state) return <section className="recipe-workspace"><p>{message || 'Opening recipes...'}</p></section>;
  const recipeAudit = source ? state.audit.filter(event => event.recipe_id === source.recipe_id) : [];
  return <section className="recipe-workspace" aria-label={edit ? 'Recipe editor' : 'Recipe viewer'}>
    <div className="recipe-heading"><h1>{edit ? 'Recipe editor' : ui('recipes')}</h1><a href={edit ? '/recipes' : '/recipe-editor'}>{edit ? 'Operator viewer' : 'Recipe editor'}</a></div>
    {hmiSecurity?.session?.configured ? <p>Recipe permissions use the signed-in HMI account.</p> : <RecipeSession session={session} onChange={setSession} />}
    <p role="status" aria-label="Recipe operation">{message}</p>
    <div className="recipe-loaded"><h2>{ui('recipeLoadedCopy')}</h2><LoadedRecipe /></div>
    <p>This HMI selection is separate from a PLC recipe transfer.</p>
    <div className="recipe-browser"><label>{ui('recipeLibrary')}<select aria-label="Recipe revision" value={source?.id || ''} onChange={event => {
      if (dirty && !window.confirm('Discard unsaved recipe changes?')) return;
      choose(state.revisions.find(revision => revision.id === Number(event.target.value)) || null);
    }}><option value="">{edit ? 'New recipe' : 'Choose recipe'}</option>{state.revisions.map(revision => <option key={revision.id} value={revision.id}>
      {revision.code} · r{revision.number} · {revision.status} · {revision.content.title}
    </option>)}</select></label>
      <button disabled={busy} onClick={() => refresh().then(next => { if (!dirty && source) choose(next.revisions.find(revision => revision.id === source.id) || source); setPolicy(next.change_policy.policy); }).catch(error => setMessage(error.message))}>Refresh recipes</button>
      {edit && <button disabled={busy} onClick={() => { if (!dirty || window.confirm('Discard unsaved recipe changes?')) choose(null); }}>New recipe</button>}
    </div>
    {source && <div className="recipe-review-state"><strong>{source.code} · r{source.number} · {source.status}</strong>
      <span>{source.status === 'approved' ? ui('recipeProduction') : ui('recipeTest')}</span>
      <span>Author: {source.author}</span>{source.approved_by && <span>Approved by: {source.approved_by} · {source.approved_at}</span>}
      </div>}
    <label className="recipe-reason">Change / approval / load reason<textarea value={reason} maxLength={1000} onChange={event => setReason(event.target.value)} /></label>
    {edit ? <>
      <fieldset disabled={!editable || busy}><legend>Recipe content — saves create a new draft revision</legend>
        <div className="recipe-content-fields"><label>Recipe code<input value={code} disabled={!!source} onChange={event => { setCode(event.target.value); setDirty(true); }} /></label>
          <label>Recipe title<input value={content.title} onChange={event => update({ ...content, title: event.target.value })} maxLength={120} /></label>
          <label>Description<textarea value={content.description} onChange={event => update({ ...content, description: event.target.value })} maxLength={2000} /></label></div>
        <div className="recipe-image-editor"><RecipePicture content={content} /><label>Recipe image (PNG/JPEG)<input type="file" accept="image/png,image/jpeg" onChange={upload} /></label>
          <button onClick={() => update({ ...content, image_id: null })}>Remove image from draft</button></div>
      </fieldset>
      <ParameterEditor content={content} update={update} disabled={!editable || busy} />
      <div className="recipe-actions"><button disabled={!editable || busy} onClick={save}>{source ? 'Save new revision' : 'Create recipe'}</button>
        {source?.status === 'draft' && <button disabled={!can('engineer') || busy || dirty || !state.gates.editing.allowed} onClick={() => transition('submit')}>Submit for approval</button>}
        {source?.status === 'in_review' && <><button disabled={!can('approver') || busy || !state.gates.approval.allowed} onClick={() => transition('approve')}>Approve for production</button>
          <button disabled={!can('approver') || busy || !state.gates.approval.allowed} onClick={() => transition('reject')}>Reject revision</button></>}
        {source?.status === 'approved' && <button disabled={!can('approver') || busy || dirty || !state.gates.approval.allowed} onClick={() => transition('withdraw')}>Withdraw approval</button>}
      </div>
      <h2>Change history</h2><table className="recipe-history"><thead><tr><th>Time / user</th><th>Action</th><th>Reason / changes</th></tr></thead><tbody>
        {recipeAudit.map(event => <tr key={event.id}><td>{event.timestamp}<br />{event.actor}</td><td>{event.operation} · revision ID {event.revision_id}</td><td>{event.details.reason}
          {event.details.changes?.map(change => <div key={change.field}><strong>{change.field}</strong>: {JSON.stringify(change.before)} → {JSON.stringify(change.after)}</div>)}</td></tr>)}
      </tbody></table>
    </> : source && <div className="recipe-preview"><RecipePicture content={source.content} /><div><h2>{source.content.title}</h2><p>{source.content.description}</p><ParameterValues content={source.content} /></div></div>}
    <div className="recipe-actions"><button disabled={busy || !source || dirty || !(can('operator') || can('engineer')) || !state.gates.loading.allowed || !live.recipeConnected} onClick={() => load()}>{ui('recipeLoad')}</button>
      <button disabled={busy || !(can('operator') || can('engineer')) || !state.gates.loading.allowed || !live.recipeConnected} onClick={() => load(true)}>{ui('recipeClear')}</button></div>
    <p>{ui('recipePlcDecision')}</p>
    <RecipeTransferPanel source={source} session={session} reason={reason} dirty={dirty} busy={busy} setBusy={setBusy} loadingAllowed={state.gates.loading.allowed} setMessage={setMessage} />
    <div className="recipe-gates">{Object.entries(state.gates).map(([operation, gate]) => <span key={operation}>{operation}: {gate.allowed ? 'allowed' : 'blocked'}{gate.permit_tag ? ` (${gate.permit_tag})` : ''}</span>)}</div>
    {edit && can('administrator') && policy && <details className="recipe-policy"><summary>Recipe change policy</summary>
      {['editing', 'approval', 'loading'].map(operation => <div key={operation}><label><input type="checkbox" checked={policy[`${operation}_enabled`]} onChange={event => setPolicy({ ...policy, [`${operation}_enabled`]: event.target.checked })} />{operation} enabled</label>
        <label>{operation} permit tag<select value={policy[`${operation}_permit_tag`] || ''} onChange={event => setPolicy({ ...policy, [`${operation}_permit_tag`]: event.target.value || null })}>
          <option value="">No application permit</option>{catalog.tags.filter(tag => tag.type === 'boolean').map(tag => <option key={tag.name}>{tag.name}</option>)}</select></label></div>)}
      <button disabled={busy} onClick={() => perform(async () => {
        const result = await api('/api/recipes/policy', json('PUT', { policy, expected_version: state.change_policy.version, reason })); setPolicy(result.policy); return result;
      })}>Save change policy</button>
      <button disabled={busy} onClick={() => perform(() => api('/api/recipes/simulator-permit', json('POST', { allowed: true, reason })))}>Set simulator recipe permit true</button>
      <button disabled={busy} onClick={() => perform(() => api('/api/recipes/simulator-permit', json('POST', { allowed: false, reason })))}>Set simulator recipe permit false</button>
      <table className="recipe-history"><tbody>{state.audit.filter(event => ['policy_changed', 'simulator_permit'].includes(event.operation)).map(event => <tr key={event.id}>
        <td>{event.timestamp}</td><td>{event.actor}</td><td>{event.operation}</td><td>{event.details.reason}</td></tr>)}</tbody></table>
    </details>}
  </section>;
}
