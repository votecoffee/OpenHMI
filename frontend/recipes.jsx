import React, { useContext, useEffect, useState } from 'react';
import { api, json } from './api.mjs';
import { RecipeSession } from './recipe-session.jsx';
import { readRecipeSession } from './recipe-auth.mjs';
import { readRecipeLibrary } from './recipe-library.mjs';
import { validatedRecipeContent, createRecipe, saveRecipeRevision, transitionRecipeRevision, selectRecipeRevision, saveRecipePolicy, uploadRecipeImage } from './recipe-api.mjs';
import { Live } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import { SecurityContext } from './security.jsx';
import { RecipeTransferPanel } from './recipe-transfers.jsx';
import { RecipePicture, LoadedRecipe, ParameterValues } from './recipe-controls.jsx';
import { ParameterEditor } from './recipe-parameters.jsx';

export { RecipePicture, LoadedRecipe, SelectedRecipe } from './recipe-controls.jsx';

const blank = () => ({ title: '', description: '', image_id: null, parameters: [] });
const clone = value => JSON.parse(JSON.stringify(value));

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
  const [libraryError, setLibraryError] = useState('');
  useEffect(() => { if (hmiSecurity?.session?.configured) setSession(hmiSecurity.session); }, [hmiSecurity?.session]);
  function choose(revision) {
    setSource(revision); setContent(revision ? clone(revision.content) : blank()); setCode(revision?.code || ''); setReason(''); setDirty(false);
  }
  async function refresh(initial = false) {
    try {
      const [next, identity] = await Promise.all([readRecipeLibrary(), readRecipeSession()]);
      setState(next); setSession(identity); setLibraryError('');
      if (initial) { choose(next.revisions[0] || null); setPolicy(next.change_policy.policy); }
      return next;
    } catch (error) { setLibraryError(error.message); throw error; }
  }
  useEffect(() => { refresh(true).catch(error => setMessage(error.message)); }, []);
  const can = role => !!session.user && (session.user.roles.includes(role) || session.user.roles.includes('administrator'));
  const blocked = busy || !!libraryError;
  const editable = !libraryError && can('engineer') && !!state?.gates.editing.allowed && source?.status !== 'in_review';
  function update(next) { setContent(next); setDirty(true); }
  async function perform(operation, acceptRevision = false) {
    setBusy(true);
    try {
      if (libraryError) throw new Error('Refresh the recipe library before another operation.');
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
      const payload = validatedRecipeContent(content);
      if (!source) return createRecipe(code, payload, reason);
      const latest = state.revisions.find(revision => revision.recipe_id === source.recipe_id);
      return saveRecipeRevision(source.recipe_id, latest.id, source.id, payload, reason);
    }, true);
  }
  function transition(action) { return perform(() => transitionRecipeRevision(source.id, action, source.version, reason), true); }
  async function load(clear = false) {
    if (!live.recipeConnected) return;
    await perform(() => selectRecipeRevision(clear ? null : source.id, clear ? null : source.version,
      live.recipeSelection.version, reason));
  }
  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      if (!reason.trim()) throw new Error('Enter an image change reason first');
      const result = await uploadRecipeImage(file, reason);
      update({ ...content, image_id: result.image_id }); setMessage('Image uploaded. Save a draft to attach it to the recipe revision.');
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); event.target.value = ''; }
  }
  if (!state) return <section className="recipe-workspace"><p role={libraryError ? 'alert' : undefined}>{libraryError ? `Recipe library unavailable: ${libraryError}` : message || 'Opening recipes...'}</p>
    {libraryError && <button onClick={() => refresh(true).catch(error => setMessage(error.message))}>Retry recipe library</button>}</section>;
  const recipeAudit = source ? state.audit.filter(event => event.recipe_id === source.recipe_id) : [];
  return <section className="recipe-workspace" aria-label={edit ? 'Recipe editor' : 'Recipe viewer'}>
    <div className="recipe-heading"><h1>{edit ? 'Recipe editor' : ui('recipes')}</h1><a href={edit ? '/recipes' : '/recipe-editor'}>{edit ? 'Operator viewer' : 'Recipe editor'}</a></div>
    {hmiSecurity?.session?.configured ? <p>Recipe permissions use the signed-in HMI account.</p> : <RecipeSession session={session} onChange={setSession} />}
    <p role="status" aria-label="Recipe operation">{message}</p>
    {libraryError && <p role="alert">Recipe library unavailable: {libraryError}. Showing the last readable library. Refresh before another operation.</p>}
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
        {source?.status === 'draft' && <button disabled={!can('engineer') || blocked || dirty || !state.gates.editing.allowed} onClick={() => transition('submit')}>Submit for approval</button>}
        {source?.status === 'in_review' && <><button disabled={!can('approver') || blocked || !state.gates.approval.allowed} onClick={() => transition('approve')}>Approve for production</button>
          <button disabled={!can('approver') || blocked || !state.gates.approval.allowed} onClick={() => transition('reject')}>Reject revision</button></>}
        {source?.status === 'approved' && <button disabled={!can('approver') || blocked || dirty || !state.gates.approval.allowed} onClick={() => transition('withdraw')}>Withdraw approval</button>}
      </div>
      <h2>Change history</h2><table className="recipe-history"><thead><tr><th>Time / user</th><th>Action</th><th>Reason / changes</th></tr></thead><tbody>
        {recipeAudit.map(event => <tr key={event.id}><td>{event.timestamp}<br />{event.actor}</td><td>{event.operation} · revision ID {event.revision_id}</td><td>{event.details.reason}
          {event.details.changes?.map(change => <div key={change.field}><strong>{change.field}</strong>: {JSON.stringify(change.before)} → {JSON.stringify(change.after)}</div>)}</td></tr>)}
      </tbody></table>
    </> : source && <div className="recipe-preview"><RecipePicture content={source.content} /><div><h2>{source.content.title}</h2><p>{source.content.description}</p><ParameterValues content={source.content} /></div></div>}
    <div className="recipe-actions"><button disabled={blocked || !source || dirty || !(can('operator') || can('engineer')) || !state.gates.loading.allowed || !live.recipeConnected} onClick={() => load()}>{ui('recipeLoad')}</button>
      <button disabled={blocked || !(can('operator') || can('engineer')) || !state.gates.loading.allowed || !live.recipeConnected} onClick={() => load(true)}>{ui('recipeClear')}</button></div>
    <p>{ui('recipePlcDecision')}</p>
    <RecipeTransferPanel source={source} session={session} reason={reason} dirty={dirty} busy={blocked} setBusy={setBusy} loadingAllowed={state.gates.loading.allowed && !libraryError} setMessage={setMessage} />
    <div className="recipe-gates">{Object.entries(state.gates).map(([operation, gate]) => <span key={operation}>{operation}: {gate.allowed ? 'allowed' : 'blocked'}{gate.permit_tag ? ` (${gate.permit_tag})` : ''}</span>)}</div>
    {edit && can('administrator') && policy && <details className="recipe-policy"><summary>Recipe change policy</summary>
      {['editing', 'approval', 'loading'].map(operation => <div key={operation}><label><input type="checkbox" checked={policy[`${operation}_enabled`]} onChange={event => setPolicy({ ...policy, [`${operation}_enabled`]: event.target.checked })} />{operation} enabled</label>
        <label>{operation} permit tag<select value={policy[`${operation}_permit_tag`] || ''} onChange={event => setPolicy({ ...policy, [`${operation}_permit_tag`]: event.target.value || null })}>
          <option value="">No application permit</option>{catalog.tags.filter(tag => tag.type === 'boolean').map(tag => <option key={tag.name}>{tag.name}</option>)}</select></label></div>)}
      <button disabled={blocked} onClick={() => perform(async () => {
        const result = await saveRecipePolicy(policy, state.change_policy.version, reason); setPolicy(result.policy); return result;
      })}>Save change policy</button>
      <button disabled={blocked} onClick={() => perform(() => api('/api/recipes/simulator-permit', json('POST', { allowed: true, reason })))}>Set simulator recipe permit true</button>
      <button disabled={blocked} onClick={() => perform(() => api('/api/recipes/simulator-permit', json('POST', { allowed: false, reason })))}>Set simulator recipe permit false</button>
      <table className="recipe-history"><tbody>{state.audit.filter(event => ['policy_changed', 'simulator_permit'].includes(event.operation)).map(event => <tr key={event.id}>
        <td>{event.timestamp}</td><td>{event.actor}</td><td>{event.operation}</td><td>{event.details.reason}</td></tr>)}</tbody></table>
    </details>}
  </section>;
}
