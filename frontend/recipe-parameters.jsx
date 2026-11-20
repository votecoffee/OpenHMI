import React from 'react';

export function ParameterEditor({ content, update, disabled }) {
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
