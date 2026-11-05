import React from 'react';

export function IdentitySettings({ settings, onChange, catalog }) {
  const config = settings.identity_publication;
  const update = fields => onChange({ ...settings, identity_publication: { ...config, ...fields } });
  const changeBit = (index, fields) => update({ bits: config.bits.map((bit, i) => i === index ? { ...bit, ...fields } : bit) });
  return <section className="engineering" aria-label="PLC identity publication"><h2>PLC identity publication</h2>
    <p>One explicitly claimed operator station publishes its authenticated user and mapped privilege bits. Applying these settings requires security administration permission. The PLC owns use of these status values and communication-loss handling.</p>
    <label><input type="checkbox" checked={config.enabled} onChange={event => update({ enabled: event.target.checked })} />Publish identity to PLC</label>
    {[['username_tag', 'PLC username STRING tag', 'string'], ['privileges_tag', 'PLC privileges DINT tag', 'integer'], ['heartbeat_tag', 'Optional PLC heartbeat DINT tag', 'integer']].map(([field, label, type]) => <label key={field}>{label}<select value={config[field] || ''} onChange={event => update({ [field]: event.target.value })}><option value="">Select writable root tag</option>{settings.tags.filter(tag => tag.type === type && tag.writable && tag.scale === 1 && tag.offset === 0).map(tag => <option key={tag.name}>{tag.name}</option>)}</select></label>)}
    <label>PLC username capacity (UTF-8 bytes)<input type="number" min="1" max="4096" value={config.username_bytes} onChange={event => update({ username_bytes: Number(event.target.value) })} /></label>
    {config.bits.map((bit, index) => <fieldset key={index}><legend>Privilege mapping {index + 1}</legend>
      <label>DINT bit<input type="number" min="0" max="31" value={bit.bit} onChange={event => changeBit(index, { bit: Number(event.target.value) })} /></label>
      <label>Bit source<select value={bit.source} onChange={event => changeBit(index, { source: event.target.value, name: '' })}><option value="permission">HMI permission</option><option value="group">HMI group membership</option></select></label>
      <label>Privilege or group<select value={bit.name} onChange={event => changeBit(index, { name: event.target.value })}><option value="">Choose source</option>{(bit.source === 'group' ? catalog.security_groups : catalog.security_permissions || []).map(name => <option key={name}>{name}</option>)}</select></label>
      <button onClick={() => update({ bits: config.bits.filter((_, i) => i !== index) })}>Remove privilege bit {bit.bit}</button></fieldset>)}
    <button disabled={config.bits.length >= 32} onClick={() => update({ bits: [...config.bits, { bit: Array.from({ length: 32 }, (_, i) => i).find(i => !config.bits.some(item => item.bit === i)), source: 'permission', name: 'runtime.operate' }] })}>Add privilege bit</button>
  </section>;
}
