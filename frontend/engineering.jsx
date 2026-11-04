import React, { useState } from 'react';
import { api } from './api.mjs';

function structureInitial(members, values) {
  const result = Object.create(null);
  for (const [path, type] of Object.entries(members)) {
    const parts = path.match(/[^.\[\]]+/g) || [];
    if (!parts.length || parts.some(part => ['__proto__', 'constructor', 'prototype'].includes(part))) throw new Error('Invalid member path');
    let parent = result;
    for (let i = 0; i < parts.length - 1; i++) parent = parent[parts[i]] ??= /^\d+$/.test(parts[i + 1]) ? [] : Object.create(null);
    parent[parts.at(-1)] = values[path] ?? (type === 'boolean' ? false : type === 'string' ? '' : 0);
  }
  return result;
}

export function engineeringCatalog(catalog, settings, template = null) {
  const tags = [...catalog.tags.filter(tag => !settings.tags?.some(item => item.name === tag.name || tag.name.startsWith(item.name + '.')))];
  for (const tag of settings.tags || []) {
    tags.push({ name: tag.name, type: tag.type === 'integer' ? 'number' : tag.type });
    for (const [member, type] of Object.entries(tag.members || {})) tags.push({ name: `${tag.name}.${member}`, type: type === 'integer' ? 'number' : type });
  }
  if (template) for (const [member, type] of Object.entries(template.members)) tags.push({ name: `$.${member}`, type: type === 'integer' ? 'number' : type });
  return { ...catalog, tags, commands: settings.commands || [], faceplates: template ? [] : settings.faceplates || [], screens: [{ id: 'overview', title: 'Overview', popup: false }, ...(settings.screens || [])] };
}

function Members({ value, change }) {
  const [name, setName] = useState('');
  const [type, setType] = useState('boolean');
  return <fieldset><legend>UDT members</legend>{Object.entries(value).map(([key, kind]) => <div key={key}>{key} · {kind} <button onClick={() => change(Object.fromEntries(Object.entries(value).filter(([member]) => member !== key)))}>Remove {key}</button></div>)}
    <label>Member path<input value={name} onChange={event => setName(event.target.value)} placeholder="Status.Running" /></label>
    <label>Member type<select value={type} onChange={event => setType(event.target.value)}>{['boolean', 'number', 'integer', 'string'].map(item => <option key={item}>{item}</option>)}</select></label>
    <button onClick={() => { if (name.trim()) { change({ ...value, [name.trim()]: type }); setName(''); } }}>Add member</button>
  </fieldset>;
}

export function EngineeringSettings({ tab, settings, onChange, editScope, catalog }) {
  const [message, setMessage] = useState('');
  const [identifier, setIdentifier] = useState('');
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [connection, setConnection] = useState('');
  const [datatype, setDatatype] = useState('number');
  const [initial, setInitial] = useState('0');
  const [members, setMembers] = useState({});
  const [memberInitial, setMemberInitial] = useState({});
  const [udt, setUdt] = useState('');
  const [browse, setBrowse] = useState([]);
  const [filter, setFilter] = useState('');
  const [popup, setPopup] = useState(false);
  const [historyTag, setHistoryTag] = useState('');
  const [sample, setSample] = useState(1000);
  const [deadband, setDeadband] = useState(0);
  function update(field, index, patch) { onChange({ ...settings, [field]: settings[field].map((item, i) => i === index ? { ...item, ...patch } : item) }); }
  function add(field, value) {
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,59}$/.test(value.id || value.name) && field !== 'tags') { setMessage('Use an ID starting with a letter, then letters, numbers, underscores or hyphens.'); return; }
    if (settings[field].some(item => (item.id || item.name) === (value.id || value.name))) { setMessage('That ID/name already exists.'); return; }
    onChange({ ...settings, [field]: [...settings[field], value] }); setIdentifier(''); setName(''); setMessage('Added to the draft. Apply live to activate.');
  }
  if (tab === 'commands') return <section className="engineering" aria-label="Command contracts"><h2>PLC command contracts</h2>
    <p>The HMI owns the request sequence. The PLC owns acceptance, completion and result (0 means success). Each command uses its own UDT channel. Timeout does not cancel or retry a command.</p>
    {(settings.commands || []).map((item, i) => <fieldset key={item.id}><legend>{item.name} ({item.id})</legend>
      <label>Command UDT<select aria-label={`${item.id} UDT`} value={item.root_tag} onChange={event => update('commands', i, { root_tag: event.target.value })}>{settings.tags.filter(tag => tag.type === 'struct' && tag.writable).map(tag => <option key={tag.name}>{tag.name}</option>)}</select></label>
      {['request_member', 'accepted_member', 'completed_member', 'result_member', 'permit_member'].map(field => <label key={field}>{field.replaceAll('_', ' ')}<select aria-label={`${item.id} ${field}`} value={item[field]} onChange={event => update('commands', i, { [field]: event.target.value })}><option value="">{field === 'permit_member' ? 'No additional permit' : 'Choose member'}</option>{Object.entries(settings.tags.find(tag => tag.name === item.root_tag)?.members || {}).filter(([, type]) => type === (field === 'permit_member' ? 'boolean' : 'integer')).map(([member]) => <option key={member}>{member}</option>)}</select></label>)}
      <label>Completion timeout (s)<input type="number" min="1" max="3600" value={item.timeout_seconds} onChange={event => update('commands', i, { timeout_seconds: Number(event.target.value) })} /></label>
      <label>Protocol update rate (ms)<input type="number" min="100" max="5000" value={item.update_ms} onChange={event => update('commands', i, { update_ms: Number(event.target.value) })} /></label>
      <label>Required HMI groups<select multiple value={item.security_groups} onChange={event => update('commands', i, { security_groups: [...event.target.selectedOptions].map(option => option.value) })}>{(catalog.security_groups || []).map(group => <option key={group}>{group}</option>)}</select></label>
      <button onClick={() => onChange({ ...settings, commands: settings.commands.filter((_, index) => index !== i) })}>Remove {item.id}</button>
    </fieldset>)}
    <label>Command ID<input value={identifier} onChange={event => setIdentifier(event.target.value)} /></label><label>Command name<input value={name} onChange={event => setName(event.target.value)} /></label>
    <label>New command UDT<select aria-label="New command UDT" value={path} onChange={event => setPath(event.target.value)}><option value="">Choose writable UDT</option>{settings.tags.filter(tag => tag.type === 'struct' && tag.writable).map(tag => <option key={tag.name}>{tag.name}</option>)}</select></label>
    <button disabled={!path} onClick={() => add('commands', { id: identifier, name: name || identifier, root_tag: path, request_member: 'RequestSequence', accepted_member: 'AcceptedSequence', completed_member: 'CompletedSequence', result_member: 'ResultCode', permit_member: '', timeout_seconds: 30, update_ms: 250, security_groups: [] })}>Add command</button><p role="status">{message}</p>
  </section>;
  if (tab === 'screens') return <section className="engineering" aria-label="Screen settings"><h2>Screens and popups</h2>
    <p>Each screen requests its own tag update rate. Shared tags use the fastest active request.</p>
    <label>Overview tag update rate (ms)<input type="number" min="100" max="60000" value={settings.update_ms} onChange={event => onChange({ ...settings, update_ms: Number(event.target.value) })} /></label>
    <button onClick={() => editScope('overview')}>Edit overview</button>
    <table><thead><tr><th>ID</th><th>Title</th><th>Update ms</th><th>Popup</th><th /></tr></thead><tbody>{settings.screens.map((screen, i) => <tr key={screen.id}><td>{screen.id}</td><td><input aria-label={`${screen.id} title`} value={screen.title} onChange={event => update('screens', i, { title: event.target.value })} /></td>
      <td><input aria-label={`${screen.id} update rate`} type="number" min="100" max="60000" value={screen.update_ms} onChange={event => update('screens', i, { update_ms: Number(event.target.value) })} /></td>
      <td>{screen.popup ? 'Popup' : 'Screen'}</td><td><button onClick={() => editScope(screen.id)}>Edit {screen.title}</button></td></tr>)}</tbody></table>
    <label>New screen ID<input value={identifier} onChange={event => setIdentifier(event.target.value)} /></label><label>New screen title<input value={name} onChange={event => setName(event.target.value)} /></label>
    <label><input type="checkbox" checked={popup} onChange={event => setPopup(event.target.checked)} />Popup screen</label>
    <button onClick={() => add('screens', { id: identifier, title: name || identifier, columns: 2, update_ms: 500, popup, controls: [] })}>Add screen</button><p role="status">{message}</p>
  </section>;
  if (tab === 'connections') return <section className="engineering" aria-label="Connection settings"><h2>ControlLogix connections</h2><p>Use a pycomm3 route such as IP/slot or IP/1/slot. Connections start disabled. Apply the draft to open enabled connections.</p>
    {settings.connections.map((item, i) => <fieldset key={item.id}><legend>{item.name} ({item.id})</legend>
      <label>Route<input aria-label={`${item.id} route`} value={item.path} onChange={event => update('connections', i, { path: event.target.value })} /></label>
      <label><input type="checkbox" checked={item.enabled} onChange={event => update('connections', i, { enabled: event.target.checked })} />Enabled</label>
      <label>Timeout seconds<input type="number" min="0.2" max="10" step="0.1" value={item.timeout_seconds} onChange={event => update('connections', i, { timeout_seconds: Number(event.target.value) })} /></label>
      <label><input type="checkbox" checked={item.program_tags} onChange={event => update('connections', i, { program_tags: event.target.checked })} />Discover program-scoped tags</label>
    </fieldset>)}
    <label>Connection ID<input value={identifier} onChange={event => setIdentifier(event.target.value)} /></label><label>Connection name<input value={name} onChange={event => setName(event.target.value)} /></label><label>PLC route<input value={path} onChange={event => setPath(event.target.value)} /></label>
    <button onClick={() => add('connections', { id: identifier, name: name || identifier, kind: 'logix', path, enabled: false, timeout_seconds: 2, program_tags: true })}>Add connection</button>
    <button onClick={async () => { try { const state = await api('/api/connections'); setMessage(JSON.stringify(state.connections, null, 2)); } catch (error) { setMessage(error.message); } }}>Refresh connection diagnostics</button><pre role="status">{message}</pre>
  </section>;
  if (tab === 'faceplates') return <section className="engineering" aria-label="Faceplate definitions"><h2>UDT faceplate definitions</h2><p>Declare member types, then design controls with relative $.Member tags. Instances bind the definition to a compatible root UDT.</p>
    {settings.faceplates.map((item, i) => <fieldset key={item.id}><legend>{item.name}</legend><label>Required UDT type<input value={item.udt_type} onChange={event => update('faceplates', i, { udt_type: event.target.value })} /></label>
      <Members value={item.members} change={next => update('faceplates', i, { members: next })} /><button onClick={() => editScope(`faceplate:${item.id}`)}>Design {item.name}</button></fieldset>)}
    <label>Faceplate ID<input value={identifier} onChange={event => setIdentifier(event.target.value)} /></label><label>Faceplate name<input value={name} onChange={event => setName(event.target.value)} /></label><label>UDT type<input value={udt} onChange={event => setUdt(event.target.value)} /></label>
    <Members value={members} change={setMembers} /><button onClick={() => add('faceplates', { id: identifier, name: name || identifier, udt_type: udt, members, controls: [] })}>Add faceplate definition</button><p role="status">{message}</p>
  </section>;
  if (tab === 'history') return <section className="engineering" aria-label="Historian settings"><h2>SQL tag history</h2>
    <label>Retention days<input type="number" min="1" max="3650" value={settings.historian.retention_days} onChange={event => onChange({ ...settings, historian: { ...settings.historian, retention_days: Number(event.target.value) } })} /></label>
    <label>Maximum history rows<input type="number" min="1000" max="10000000" value={settings.historian.max_rows} onChange={event => onChange({ ...settings, historian: { ...settings.historian, max_rows: Number(event.target.value) } })} /></label>
    <table><thead><tr><th>Tag</th><th>Sample ms</th><th>Deadband</th><th /></tr></thead><tbody>{settings.historian.tags.map((item, i) => <tr key={item.tag}><td>{item.tag}</td><td>{item.sample_ms}</td><td>{item.deadband}</td><td><button onClick={() => onChange({ ...settings, historian: { ...settings.historian, tags: settings.historian.tags.filter((_, index) => index !== i) } })}>Remove {item.tag}</button></td></tr>)}</tbody></table>
    <label>History tag<input value={historyTag} onChange={event => setHistoryTag(event.target.value)} /></label><label>Sample interval (ms)<input type="number" min="100" value={sample} onChange={event => setSample(Number(event.target.value))} /></label><label>Deadband<input type="number" min="0" step="any" value={deadband} onChange={event => setDeadband(Number(event.target.value))} /></label>
    <button onClick={() => { if (historyTag && !settings.historian.tags.some(item => item.tag === historyTag)) onChange({ ...settings, historian: { ...settings.historian, tags: [...settings.historian.tags, { tag: historyTag, sample_ms: sample, deadband }] } }); }}>Add history tag</button>
  </section>;
  return <section className="engineering" aria-label="Tag manager"><h2>Tag manager</h2><p>Logical names keep screens independent of PLC addresses. Built-in simulation tags remain available.</p>
    <label>Browse connection<select value={connection} onChange={event => setConnection(event.target.value)}><option value="">Local HMI tags</option>{settings.connections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <button disabled={!connection} onClick={async () => { try { const state = await api(`/api/connections/${connection}/browse`); setBrowse(state.tags); setMessage(state.error || `${state.tags.length} PLC tags available`); } catch (error) { setMessage(error.message); } }}>Browse PLC tags</button>
    <label>Filter PLC tags<input value={filter} onChange={event => setFilter(event.target.value)} /></label>
    {browse.length > 0 && <select aria-label="PLC tag" size="6" onChange={event => { const tag = browse.find(item => item.address === event.target.value); if (tag) { setPath(tag.address); setDatatype(tag.type); setMembers(tag.members || {}); setUdt(tag.udt_type || ''); } }}>{browse.filter(item => item.address.toLowerCase().includes(filter.toLowerCase())).slice(0, 500).map(item => <option key={item.address} value={item.address}>{item.address} · {item.udt_type || item.type}</option>)}</select>}
    <label>Logical tag name<input value={name} onChange={event => setName(event.target.value)} /></label><label>PLC address<input disabled={!connection} value={path} onChange={event => setPath(event.target.value)} /></label>
    <label>Tag type<select value={datatype} onChange={event => { setDatatype(event.target.value); setInitial(event.target.value === 'boolean' ? 'false' : event.target.value === 'struct' ? '{}' : '0'); }}>{['boolean', 'number', 'integer', 'string', 'struct'].map(type => <option key={type}>{type}</option>)}</select></label>
    {!connection && datatype !== 'struct' && <label>Initial value<input type={datatype === 'boolean' ? 'checkbox' : datatype === 'string' ? 'text' : 'number'} value={initial} checked={datatype === 'boolean' ? initial === 'true' : undefined} onChange={event => setInitial(datatype === 'boolean' ? String(event.target.checked) : event.target.value)} /></label>}
    {datatype === 'struct' && <><label>Tag UDT type<input value={udt} onChange={event => setUdt(event.target.value)} /></label><Members value={members} change={setMembers} /></>}
    {!connection && datatype === 'struct' && <fieldset><legend>Initial member values</legend>{Object.entries(members).map(([member, type]) => <label key={member}>{member}<input aria-label={`${member} initial value`} type={type === 'boolean' ? 'checkbox' : type === 'string' ? 'text' : 'number'} checked={type === 'boolean' ? !!memberInitial[member] : undefined} value={memberInitial[member] ?? (type === 'string' ? '' : 0)} onChange={event => setMemberInitial({ ...memberInitial, [member]: type === 'boolean' ? event.target.checked : type === 'string' ? event.target.value : Number(event.target.value) })} /></label>)}</fieldset>}
    <button onClick={() => { try { const value = connection ? 0 : datatype === 'struct' ? structureInitial(members, memberInitial) : datatype === 'string' ? initial : datatype === 'boolean' ? initial === 'true' : Number(initial); add('tags', { name, connection, address: connection ? path : '', type: datatype, initial: value, writable: false, scale: 1, offset: 0, members: datatype === 'struct' ? members : {}, udt_type: datatype === 'struct' ? udt : '' }); } catch { setMessage('Initial value must match the selected type.'); } }}>Add tag</button>
    <table><thead><tr><th>Logical tag</th><th>Source / address</th><th>Type</th><th>Writable</th><th>Scale</th><th>Offset</th></tr></thead><tbody>{settings.tags.map((tag, i) => <tr key={tag.name}><td>{tag.name}</td><td>{tag.connection || 'Local'} / {tag.address}</td><td>{tag.udt_type || tag.type}</td>
      <td><input aria-label={`${tag.name} writable`} type="checkbox" checked={tag.writable} onChange={event => update('tags', i, { writable: event.target.checked })} /></td>
      <td><input aria-label={`${tag.name} scale`} type="number" step="any" disabled={!tag.connection || !['number', 'integer'].includes(tag.type)} value={tag.scale} onChange={event => update('tags', i, { scale: Number(event.target.value) })} /></td>
      <td><input aria-label={`${tag.name} offset`} type="number" step="any" disabled={!tag.connection || !['number', 'integer'].includes(tag.type)} value={tag.offset} onChange={event => update('tags', i, { offset: Number(event.target.value) })} /></td></tr>)}</tbody></table><p role="status">{message}</p>
  </section>;
}
