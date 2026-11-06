import React, { useState } from 'react';
import { uiText } from './localization.jsx';

export function getSettings(project) {
  return { identity_publication: project.identity_publication || { enabled: false, username_tag: '', privileges_tag: '', username_bytes: 82, bits: [] }, languages: project.languages || [{ code: 'en', name: 'English', flag: 'us', direction: 'ltr', translations: {} }],
    default_language: project.default_language || 'en', alarms: project.alarms || [], alarm_history_limit: project.alarm_history_limit || 1000,
    screens: project.screens || [], faceplates: project.faceplates || [], connections: project.connections || [], tags: project.tags || [],
    commands: project.commands || [], recipe_transfers: project.recipe_transfers || [], update_ms: project.update_ms || 500, historian: project.historian || { tags: [], retention_days: 30, max_rows: 1000000 } };
}

export function ProjectSettings({ tab, settings, controls, title, catalog, onChange }) {
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [flag, setFlag] = useState('cn');
  const [selected, setSelected] = useState(settings.default_language);
  const [error, setError] = useState('');
  const language = settings.languages.find(item => item.code === selected) || settings.languages[0];
  function updateLanguage(next) {
    onChange({ ...settings, languages: settings.languages.map(item => item.code === language.code ? next : item) });
  }
  function addLanguage(event) {
    event.preventDefault();
    if (!/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(code) || !name.trim() || settings.languages.some(item => item.code.toLowerCase() === code.toLowerCase())) {
      setError('Enter a unique language code and a language name.'); return;
    }
    onChange({ ...settings, languages: [...settings.languages, { code, name: name.trim(), flag, direction: 'ltr', translations: {} }] });
    setSelected(code); setCode(''); setName(''); setError('');
  }
  function controlEntries(control, id) {
    const key = `control.${id}`;
    return [
      [key + '.label', control.label],
      ...['unit', 'x_unit', 'y_unit'].filter(field => field in control).map(field => [key + '.' + field, control[field]]),
      ...(control.kind === 'indicator' ? [[key + '.on_text', control.on_text || 'ON'], [key + '.off_text', control.off_text || 'OFF']] : []),
      ...(control.states || []).map(state => [`${key}.state.${state.value}`, state.label]),
      ...(control.options || []).map((option, index) => [`${key}.choice.${index}`, option.label]),
      ...(control.lamps || []).map((lamp, index) => [`${key}.lamp.${index}`, lamp.label]),
      ...(control.checks || []).map((check, index) => [`${key}.check.${index}`, check.label]),
      ...(Array.isArray(control.series) ? control.series.flatMap((series, index) => [
        [`${key}.series.${index}.label`, series.label || series.tag || `${series.x_tag} / ${series.y_tag}`],
        ...('unit' in series ? [[`${key}.series.${index}.unit`, series.unit]] : []),
      ]) : []),
    ];
  }
  const entries = [['screen.title', title], ...controls.flatMap(control => controlEntries(control, control.id)),
    ...(settings.screens || []).flatMap(screen => [[`screen.${screen.id}.title`, screen.title],
      ...screen.controls.flatMap(control => controlEntries(control, `${screen.id}__${control.id}`))]),
    ...settings.alarms.flatMap(alarm => [['message', alarm.message], ['cause', alarm.cause || ''], ['response', alarm.response || '']].map(([field, value]) => [`alarm.${alarm.id}.${field}`, value])), ...Object.entries(uiText).map(([key, value]) => [`ui.${key}`, value])];
  function updateAlarm(index, change) { onChange({ ...settings, alarms: settings.alarms.map((alarm, i) => i === index ? { ...alarm, ...change } : alarm) }); }
  if (tab === 'languages') return <section className="project-settings" aria-label="Language settings">
    <h2>Project languages</h2><p>Only added languages appear in the runtime flag selector. Empty translations use the source text.</p>
    <form className="settings-add" onSubmit={addLanguage}>
      <label>Language code<input aria-label="New language code" placeholder="zh-CN" value={code} onChange={event => setCode(event.target.value)} maxLength={35} /></label>
      <label>Language name<input aria-label="New language name" placeholder="简体中文" value={name} onChange={event => setName(event.target.value)} maxLength={60} /></label>
      <label>Flag<select aria-label="New language flag" value={flag} onChange={event => setFlag(event.target.value)}>{catalog.flags.map(value => <option key={value}>{value}</option>)}</select></label>
      <img className="flag-preview" src={`/static/assets/flags/${flag}.svg`} alt="Selected flag" /><button>Add language</button>
    </form>{error && <p role="alert">{error}</p>}
    <label>Default language<select value={settings.default_language} onChange={event => onChange({ ...settings, default_language: event.target.value })}>
      {settings.languages.map(item => <option key={item.code} value={item.code}>{item.name}</option>)}
    </select></label>
    <div className="language-list">{settings.languages.map(item => <div key={item.code}>
      <img src={`/static/assets/flags/${item.flag}.svg`} alt="" /><span>{item.name} ({item.code})</span>
      <button disabled={item.code === settings.default_language} onClick={() => onChange({ ...settings, languages: settings.languages.filter(language => language.code !== item.code) })}>Remove {item.name}</button>
    </div>)}</div>
    <h3>Translations</h3><label>Translation language<select value={language.code} onChange={event => setSelected(event.target.value)}>
      {settings.languages.map(item => <option key={item.code} value={item.code}>{item.name}</option>)}
    </select></label>
    <label>Text direction<select value={language.direction || 'ltr'} onChange={event => updateLanguage({ ...language, direction: event.target.value })}>
      <option value="ltr">Left to right</option><option value="rtl">Right to left</option></select></label>
    <table><thead><tr><th>Text key</th><th>Source</th><th>{language.name}</th></tr></thead><tbody>
      {entries.map(([key, source]) => <tr key={key}><td>{key}</td><td>{source}</td><td><input aria-label={`${key} translation`} value={language.translations?.[key] || ''} maxLength={2000}
        onChange={event => updateLanguage({ ...language, translations: { ...language.translations, [key]: event.target.value } })} /></td></tr>)}
    </tbody></table>
  </section>;
  return <section className="project-settings" aria-label="Alarm setup">
    <h2>Alarm tag monitoring</h2><p>These project-wide triggers run on the Python server. Changes take effect with Apply live. Bit positions are 1–32 (position 1 is bit 0).</p>
    <label>Completed history limit<input type="number" min="50" max="10000" value={settings.alarm_history_limit} onChange={event => onChange({ ...settings, alarm_history_limit: Number(event.target.value) })} /></label>
    <button onClick={() => {
      let index = settings.alarms.length + 1;
      while (settings.alarms.some(alarm => alarm.id === `alarm_${index}`)) ++index;
      onChange({ ...settings, alarms: [...settings.alarms, { id: `alarm_${index}`, tag: 'ProcessAlarm', trigger_type: 'value', trigger_value: 1, message: 'New alarm', priority: 2, ack_required: true, enabled: true }] });
    }}>Add alarm</button>
    {settings.alarms.map((alarm, index) => <fieldset key={index}><legend>{alarm.id}</legend><div className="alarm-fields">
      <label>Alarm ID<input value={alarm.id} maxLength={100} onChange={event => updateAlarm(index, { id: event.target.value })} /></label>
      <label>Trigger tag<select value={alarm.tag} onChange={event => updateAlarm(index, { tag: event.target.value })}>{catalog.tags.map(tag => <option key={tag.name}>{tag.name}</option>)}</select></label>
      <label>Trigger type<select value={alarm.trigger_type} onChange={event => updateAlarm(index, { trigger_type: event.target.value })}>{['value', 'bit', 'lsbit'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Trigger value / bit position<input type="number" value={alarm.trigger_value} onChange={event => updateAlarm(index, { trigger_value: Number(event.target.value) })} /></label>
      <label>Alarm message<input value={alarm.message} maxLength={500} onChange={event => updateAlarm(index, { message: event.target.value })} /></label>
      <label>Possible cause<textarea aria-label={`${alarm.id} cause`} value={alarm.cause || ''} maxLength={2000} onChange={event => updateAlarm(index, { cause: event.target.value })} /></label>
      <label>Recovery steps<textarea aria-label={`${alarm.id} recovery steps`} rows={4} placeholder="Enter one recovery step per line." value={alarm.response || ''} maxLength={2000} onChange={event => updateAlarm(index, { response: event.target.value })} /></label>
      <label>Related screen<select aria-label={`${alarm.id} related screen`} value={alarm.related_screen || ''} onChange={event => updateAlarm(index, { related_screen: event.target.value })}><option value="">No related screen</option>{catalog.screens.filter(screen => !screen.popup).map(screen => <option key={screen.id} value={screen.id}>{screen.title}</option>)}</select></label>
      <label>Priority<select value={alarm.priority} onChange={event => updateAlarm(index, { priority: Number(event.target.value) })}>{[1, 2, 3, 4].map(value => <option key={value}>{value}</option>)}</select></label>
      <label><input type="checkbox" checked={alarm.ack_required} onChange={event => updateAlarm(index, { ack_required: event.target.checked })} />Acknowledgement required</label>
      <label><input type="checkbox" checked={alarm.enabled} onChange={event => updateAlarm(index, { enabled: event.target.checked })} />Enabled</label>
      <button onClick={() => onChange({ ...settings, alarms: settings.alarms.filter((_, i) => i !== index) })}>Remove alarm {alarm.id}</button>
    </div></fieldset>)}
  </section>;
}
