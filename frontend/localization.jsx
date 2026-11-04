import React, { createContext, useContext, useEffect, useState } from 'react';

export const uiText = {
  simulation: 'SIMULATION', localStation: 'LOCAL STATION', dataConnected: 'Data connected', commLoss: 'COMM LOSS',
  badData: 'BAD DATA', badRange: 'BAD RANGE', on: 'ON', off: 'OFF', state: 'STATE', textShape: 'Text + shape',
  inactive: 'INACTIVE', active: 'ACTIVE', normal: 'Normal', outOfScale: 'OUT OF SCALE', outsideBand: 'OUTSIDE NORMAL BAND',
  overview: 'OVERVIEW', localSimulator: 'LOCAL SIMULATOR', preview: 'PREVIEW', editScreen: 'EDIT SCREEN',
  alarmUnavailable: 'ALARM MONITOR UNAVAILABLE', noAlarms: 'No alarms configured', noActiveAlarms: 'No active or unacknowledged alarms',
  activeAlarms: '{active} active / {unack} unacknowledged', alarms: 'ALARMS', acknowledge: 'Acknowledge', acknowledgeAll: 'Acknowledge all',
  returned: 'Returned', retired: 'Retired', unacknowledged: 'Unacknowledged', acknowledged: 'Acknowledged',
  alarmHistory: 'Alarm history', alarmStatus: 'Alarm status', message: 'Message', priority: 'Priority', status: 'Status',
  raised: 'Raised', time: 'Time', event: 'Event', quality_bad: 'Bad trigger data', quality_recovered: 'Trigger data recovered',
  configuration_changed: 'Configuration changed', noOutstanding: 'No outstanding alarms', noHistory: 'No alarm events',
  working: 'Working...', pending: 'Command pending', completed: 'Action completed', configureAction: 'Select to configure action',
  recipes: 'Recipes', recipeNoImage: 'No recipe image', recipeUnavailable: 'Recipe selection unavailable', recipeNotLoaded: 'No recipe loaded',
  recipeRevision: 'Revision', recipeProduction: 'PRODUCTION APPROVED', recipeTest: 'NOT PRODUCTION APPROVED', recipeLoadedBy: 'Loaded by',
  recipeApprovedBy: 'Approved by', recipeParameter: 'Parameter', recipeValue: 'Value', recipeUnits: 'Units', recipeLoadedCopy: 'Loaded copy',
  recipeLibrary: 'Recipe library / revision', recipeLoad: 'Load recipe', recipeClear: 'Clear loaded copy',
  recipePlcDecision: 'Production approval travels with the loaded copy. The PLC decides whether to run, reject parts or inhibit operation.',
};
const Context = createContext(null);
const english = { code: 'en', name: 'English', flag: 'us', direction: 'ltr', translations: {} };

export function Localization({ project, children }) {
  const languages = project.languages?.length ? project.languages : [english];
  const [code, setCode] = useState(() => {
    try { return localStorage.getItem('openhmi.language') || project.default_language || 'en'; }
    catch { return project.default_language || 'en'; }
  });
  const language = languages.find(item => item.code === code)
    || languages.find(item => item.code === project.default_language) || languages[0];
  useEffect(() => {
    document.documentElement.lang = language.code;
    document.documentElement.dir = language.direction || 'ltr';
  }, [language.code, language.direction]);
  function choose(next) {
    setCode(next);
    try { localStorage.setItem('openhmi.language', next); } catch { /* Selection still works without storage. */ }
  }
  function text(key, fallback, params = {}) {
    const value = language.translations?.[key] || (fallback ?? key);
    return value.replace(/\{(\w+)\}/g, (match, name) => Object.hasOwn(params, name) ? String(params[name]) : match);
  }
  return <Context.Provider value={{ language, languages, choose, text, ui: (key, params) => text(`ui.${key}`, uiText[key], params) }}>{children}</Context.Provider>;
}

export function useLocalization() { return useContext(Context); }

export function LanguageSelector() {
  const { language, languages, choose } = useLocalization();
  const [open, setOpen] = useState(false);
  const others = languages.filter(item => item.code !== language.code);
  return <div className="language-selector" onKeyDown={event => { if (event.key === 'Escape') setOpen(false); }}>
    <button className="language-button" aria-label={`Language: ${language.name}`} aria-expanded={open && !!others.length}
      aria-haspopup="menu" disabled={!others.length} onClick={() => setOpen(!open)}>
      <img src={`/static/assets/flags/${language.flag}.svg`} alt={language.name} /><span aria-hidden="true">▾</span>
    </button>
    {open && !!others.length && <div className="language-menu" role="menu" aria-label="Configured languages">
      {others.map(item => <button key={item.code} role="menuitem" lang={item.code} onClick={() => { choose(item.code); setOpen(false); }}>
        <img src={`/static/assets/flags/${item.flag}.svg`} alt="" /><span>{item.name}</span>
      </button>)}
    </div>}
  </div>;
}

export function alarmMessage(alarm, language) { return alarm.messages?.[language.code] || alarm.message; }
