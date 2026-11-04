import React, { createContext, useContext, useEffect, useState } from 'react';
import { api, json } from './api.mjs';

export const SecurityContext = createContext(null);
export function allowed(session, permission, groups = []) {
  if (!session) return false;
  if (!session.configured && !groups.length) return true;
  const user = session.user;
  return !!user?.permissions.includes(permission) && (!groups.length || user.permissions.includes('security.manage') || groups.some(group => user.groups.includes(group)));
}

export function SecurityBar({ session, refresh }) {
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [provider, setProvider] = useState('local');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  async function login(event) {
    event.preventDefault(); setBusy(true); setMessage('');
    try { await api('/api/security/login', json('POST', { name, password, provider })); await refresh(); }
    catch (error) { setMessage(error.message); }
    finally { setPassword(''); setBusy(false); }
  }
  return <section className="security-bar" aria-label="HMI login">
    {!session ? <span>Login status unavailable — controls are locked.</span> : session.user ? <>
      <span>Signed in: <strong>{session.user.name}</strong> ({session.user.provider}) · {session.user.groups.join(', ')}</span>
      <button disabled={busy} onClick={async () => { setBusy(true); try { await api('/api/security/logout', json('POST', {})); await refresh(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }}>Sign out of HMI</button>
    </> : session.configured ? <form onSubmit={login}>
      <label>Account type<select value={provider} onChange={event => setProvider(event.target.value)}><option value="local">Local HMI account</option>{session.windows_enabled && session.windows_available && <option value="windows">Windows account</option>}</select></label>
      <label>HMI user<input autoComplete="username" value={name} onChange={event => setName(event.target.value)} required /></label>
      <label>HMI password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label>
      <button disabled={busy}>Sign in to HMI</button>
    </form> : <span>Unsecured simulation — create an administrator with openhmi-security to enable HMI login.</span>}
    <a href="/security">Security</a>{message && <span role="alert">{message}</span>}
  </section>;
}

function Choices({ label, options, value, onChange }) {
  return <fieldset><legend>{label}</legend>{options.map(option => <label key={option}><input type="checkbox" checked={value.includes(option)} onChange={event => onChange(event.target.checked ? [...value, option] : value.filter(item => item !== option))} />{option}</label>)}</fieldset>;
}

export function SecurityAdmin() {
  const { session } = useContext(SecurityContext);
  const [state, setState] = useState(null);
  const [message, setMessage] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [group, setGroup] = useState('');
  const [permissions, setPermissions] = useState([]);
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [groups, setGroups] = useState([]);
  const [enabled, setEnabled] = useState(true);
  const [account, setAccount] = useState('');
  const [kind, setKind] = useState('group');
  const [target, setTarget] = useState('Operators');
  const canManage = !!session?.user?.permissions.includes('security.manage');
  async function refresh() { try { setState(await api('/api/security')); } catch (error) { setMessage(error.message); } }
  useEffect(() => { if (canManage) refresh(); else setState(null); }, [canManage]);
  async function change(fields) {
    if (!reason.trim()) { setMessage('Enter a security change reason.'); return; }
    setBusy(true);
    try { setState(await api('/api/security', json('PUT', { ...fields, reason, expected_version: state.version }))); setMessage('Security change recorded.'); setReason(''); setPassword(''); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  if (!canManage || !state) return <section className="security-admin"><h1>HMI security</h1><p>Sign in with a security administrator account to manage users, HMI groups and Windows assignments.</p><p>{message}</p></section>;
  const names = state.groups.map(item => item.name);
  return <section className="security-admin"><h1>HMI security</h1>
    <p>HMI groups define permissions. Assign local users, Windows users or Windows groups to them. Screen controls can require membership in any selected HMI group.</p>
    <button disabled={busy} onClick={refresh}>Refresh security</button><p role="status" aria-label="Security operation">{message}</p>
    <label>Security change reason<textarea value={reason} onChange={event => setReason(event.target.value)} maxLength={1000} /></label>
    <fieldset disabled={busy}><legend>HMI groups</legend>
      <label>Edit existing group<select value={names.includes(group) ? group : ''} onChange={event => { const found = state.groups.find(item => item.name === event.target.value); setGroup(found?.name || ''); setPermissions(found?.permissions || []); }}><option value="">New group</option>{names.map(name => <option key={name}>{name}</option>)}</select></label>
      <label>HMI group name<input value={group} onChange={event => setGroup(event.target.value)} maxLength={60} /></label>
      <Choices label="Group permissions" options={state.permissions} value={permissions} onChange={setPermissions} />
      <button onClick={() => change({ operation: 'group', name: group, permissions })}>Save HMI group</button>
    </fieldset>
    <fieldset disabled={busy}><legend>Local HMI users</legend>
      <label>Edit local user<select value={state.users.some(item => item.name === user) ? user : ''} onChange={event => { const found = state.users.find(item => item.name === event.target.value); setUser(found?.name || ''); setGroups(found?.groups || []); setEnabled(found?.enabled ?? true); setPassword(''); }}><option value="">New user</option>{state.users.map(item => <option key={item.name}>{item.name}</option>)}</select></label>
      <label>Local user name<input value={user} onChange={event => setUser(event.target.value)} maxLength={60} autoComplete="off" /></label>
      <label>New password (leave blank to retain existing)<input type="password" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} /></label>
      <label><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />User enabled</label>
      <Choices label="User HMI groups" options={names} value={groups} onChange={setGroups} />
      <button onClick={() => change({ operation: 'user', name: user, groups, enabled, password: password || null })}>Save local user</button>
    </fieldset>
    <fieldset disabled={busy}><legend>Windows users and groups</legend>
      <p>Windows credentials are verified on the server. Assignments are stored by SID. Domain membership comes from the Windows logon token.</p>
      <button disabled={!state.windows_available} onClick={() => change({ operation: 'windows', enabled: !state.windows_enabled })}>{state.windows_enabled ? 'Disable' : 'Enable'} Windows login</button>
      {!state.windows_available && <p>Windows login requires a Windows server.</p>}
      <label>Windows identity<input placeholder="DOMAIN\Account" value={account} onChange={event => setAccount(event.target.value)} /></label>
      <label>Windows identity type<select value={kind} onChange={event => setKind(event.target.value)}><option value="group">Windows group</option><option value="user">Windows user</option></select></label>
      <label>Assign to HMI group<select value={target} onChange={event => setTarget(event.target.value)}>{names.map(name => <option key={name}>{name}</option>)}</select></label>
      <button disabled={!state.windows_available} onClick={() => change({ operation: 'binding', account, kind, group: target })}>Add Windows assignment</button>
      <table><thead><tr><th>Windows identity</th><th>Type</th><th>HMI group</th><th /></tr></thead><tbody>{state.bindings.map(binding => <tr key={`${binding.sid}-${binding.kind}-${binding.group}`}><td>{binding.label}</td><td>{binding.kind}</td><td>{binding.group}</td><td><button onClick={() => change({ operation: 'unbind', sid: binding.sid, kind: binding.kind, group: binding.group })}>Remove assignment</button></td></tr>)}</tbody></table>
    </fieldset>
    <h2>Security history</h2><table><thead><tr><th>Time</th><th>User</th><th>Change</th><th>Reason</th></tr></thead><tbody>{state.audit.map((event, index) => <tr key={index}><td>{event.timestamp}</td><td>{event.actor}</td><td>{event.operation} {event.details.name || event.details.account}</td><td>{event.details.reason}</td></tr>)}</tbody></table>
  </section>;
}
