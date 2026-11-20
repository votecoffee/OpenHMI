import React, { useState } from 'react';
import { signInRecipe, signOutRecipe } from './recipe-auth.mjs';

export function RecipeSession({ session, onChange }) {
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function signIn(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await signInRecipe(name, password);
      setPassword(''); onChange({ ...session, user: result.user });
    } catch (problem) { setError(problem.message); }
    finally { setBusy(false); }
  }
  return <div className="recipe-session">
    {session.user ? <><span>Signed in: <strong>{session.user.name}</strong> ({session.user.roles.join(', ')})</span>
      <button onClick={async () => { try { await signOutRecipe(); onChange({ ...session, user: null }); } catch (problem) { setError(problem.message); } }}>Sign out</button></>
      : session.configured ? <form onSubmit={signIn}><label>Recipe user<input autoComplete="username" value={name} onChange={event => setName(event.target.value)} /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></label>
        <button disabled={busy}>Sign in</button></form>
      : <p>Recipe accounts are not configured. An administrator can create them with openhmi-users and restart OpenHMI.</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
