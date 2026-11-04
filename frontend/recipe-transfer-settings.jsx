import React, { useState } from 'react';

const metadata = ['RecipeCode', 'RevisionId', 'RevisionNumber', 'ContentHash', 'TransferHash', 'RecipeProductionApproved'];

function Mapping({ profile, root, change }) {
  const [name, setName] = useState('');
  const [member, setMember] = useState('');
  const options = Object.entries(root?.members || {}).filter(([path, kind]) => path.startsWith(profile.staging_prefix + '.') && root.members[profile.running_prefix + path.slice(profile.staging_prefix.length)] === kind)
    .map(([path, kind]) => [path.slice(profile.staging_prefix.length + 1), kind]).filter(([path]) => !metadata.includes(path));
  return <fieldset><legend>Recipe parameter mapping</legend><table><thead><tr><th>Recipe parameter</th><th>Staging / running member</th><th /></tr></thead><tbody>{Object.entries(profile.parameters).map(([parameter, path]) => <tr key={parameter}><td>{parameter}</td><td>{path}</td><td><button onClick={() => change({ ...profile, parameters: Object.fromEntries(Object.entries(profile.parameters).filter(([key]) => key !== parameter)) })}>Remove {parameter}</button></td></tr>)}</tbody></table>
    <label>Recipe parameter name<input aria-label={`${profile.id} parameter name`} value={name} onChange={event => setName(event.target.value)} /></label>
    <label>Parameter member<select aria-label={`${profile.id} parameter member`} value={member} onChange={event => setMember(event.target.value)}><option value="">Choose matched member</option>{options.map(([path, kind]) => <option key={path} value={path}>{path} · {kind}</option>)}</select></label>
    <button disabled={!/^[A-Za-z][A-Za-z0-9_]{0,59}$/.test(name) || !member} onClick={() => { change({ ...profile, parameters: { ...profile.parameters, [name]: member } }); setName(''); setMember(''); }}>Add parameter mapping</button>
  </fieldset>;
}

export function RecipeTransferSettings({ settings, onChange }) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [command, setCommand] = useState('');
  const [error, setError] = useState('');
  const profiles = settings.recipe_transfers || [];
  function change(index, value) { onChange({ ...settings, recipe_transfers: profiles.map((item, i) => i === index ? value : item) }); }
  return <section className="engineering" aria-label="Recipe transfer settings"><h2>PLC recipe transfer profiles</h2>
    <p>Use a dedicated command UDT with separate staging and running members. The HMI verifies staging and sends the commit last. The PLC owns its running copy and publishes completion. Test recipes transfer with production status false.</p>
    <p>Each prefix must declare {metadata.join(', ')} plus the mapped parameter members. Configure the command's PLC permit and HMI groups in Commands.</p>
    {profiles.map((profile, index) => {
      const definition = settings.commands.find(item => item.id === profile.command_id);
      const root = settings.tags.find(item => item.name === definition?.root_tag);
      return <fieldset key={profile.id}><legend>{profile.name} ({profile.id})</legend><p>Commit command: {definition?.name || profile.command_id} · UDT: {definition?.root_tag}</p>
        {['staging_prefix', 'running_prefix'].map(field => <label key={field}>{field.replaceAll('_', ' ')}<input aria-label={`${profile.id} ${field}`} value={profile[field]} onChange={event => change(index, { ...profile, [field]: event.target.value })} /></label>)}
        <label>PLC string length<input aria-label={`${profile.id} string length`} type="number" min="64" max="1000" value={profile.max_string_length} onChange={event => change(index, { ...profile, max_string_length: Number(event.target.value) })} /></label>
        <Mapping profile={profile} root={root} change={value => change(index, value)} /><button onClick={() => onChange({ ...settings, recipe_transfers: profiles.filter((_, i) => i !== index) })}>Remove transfer {profile.id}</button>
      </fieldset>;
    })}
    <label>Transfer profile ID<input value={id} onChange={event => setId(event.target.value)} /></label><label>Transfer profile name<input value={name} onChange={event => setName(event.target.value)} /></label>
    <label>Commit command<select aria-label="Commit command" value={command} onChange={event => setCommand(event.target.value)}><option value="">Choose dedicated command</option>{settings.commands.filter(item => !profiles.some(profile => profile.command_id === item.id)).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <button disabled={!command} onClick={() => { if (!/^[A-Za-z][A-Za-z0-9_-]{0,59}$/.test(id) || profiles.some(item => item.id === id)) { setError('Enter a unique profile ID starting with a letter.'); return; } onChange({ ...settings, recipe_transfers: [...profiles, { id, name: name || id, command_id: command, staging_prefix: 'Staging', running_prefix: 'Running', parameters: {}, max_string_length: 82 }] }); setId(''); setName(''); setCommand(''); setError(''); }}>Add transfer profile</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
