import React, { createContext, useContext, useEffect, useState } from 'react';

export const uiText = {
  alarmShelving: 'Alarm shelving', shelfExplanation: 'Shelving applies to this alarm and its retriggers until expiry. Monitoring and history continue. Global counts and Acknowledge all include shelved alarms. This registry is independent of list filters.',
  shelfReason: 'Reason for shelving or restoring', shelfDuration: 'Shelf duration', shelfMinutes: '{count} minutes', shelfExpiry: 'Shelved until',
  shelfFilter: 'Shelving filter', unshelved: 'Unshelved', shelved: 'Shelved', allShelving: 'All shelving states',
  noShelves: 'No active shelves on this page', firstShelves: 'First shelves', moreShelves: 'More shelves', shelveAlarm: 'Shelve this alarm',
  restoreAlarm: 'Restore alarm', restoreAlarmNamed: 'Restore {name}', shelfSaved: 'Alarm shelved', shelfRestored: 'Alarm restored',
  shelf_restored: 'Shelf restored', shelf_expired: 'Shelf expired', shelf_invalidated: 'Shelf invalidated by configuration',
  shelvedSummary: 'Shelved alarm definitions: {count}', noUnshelvedAlarms: 'No unshelved outstanding alarms', shelfPending: 'Shelf operation completed; activity finalization pending. Operation {id}',
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
  alarmSearch: 'Alarm search', alarmStateFilter: 'Occurrence state', allPriorities: 'All priorities', allStates: 'All states', outstanding: 'Outstanding',
  filterAlarms: 'Apply alarm filters', alarmStart: 'Start time', alarmEnd: 'End time', selectAlarm: 'Select occurrence {id}',
  selectAlarmPage: 'Select unacknowledged on this page', acknowledgeSelected: 'Acknowledge selected', selectedCount: '{count} selected',
  acknowledgementComment: 'Acknowledgement comment', acknowledgedCount: '{count} alarms acknowledged', acknowledgedBy: 'Acknowledged by',
  alarmDetails: 'Alarm details', inspectAlarm: 'Details {id}', triggerQuality: 'Current trigger quality', possibleCause: 'Possible cause', operatorResponse: 'Recovery steps',
  noGuidance: 'No guidance configured for this occurrence', openRelatedScreen: 'Open related screen', relatedScreenUnavailable: 'Related screen unavailable in the active project',
  operatorNotes: 'Operator notes', operatorNote: 'Operator note', saveOperatorNote: 'Save operator note', noteSaved: 'Operator note recorded', operator_note: 'Operator note',
  olderAlarms: 'Older alarms', newestAlarms: 'Newest alarms', olderEvents: 'Older events', newestEvents: 'Newest events', olderNotes: 'Older notes', newestNotes: 'Newest notes',
  alarmEventFilter: 'Event filter', allEvents: 'All events', exportAlarmCsv: 'Export alarm events CSV', alarmHistoryHint: 'History shares priority, search and time filters; occurrence state applies to the alarm list only.',
  alarmCountsHint: 'Global counts include all outstanding alarms, independent of these filters. Acknowledge all includes every unacknowledged occurrence.',
  alarmFilteredEmpty: 'No alarms match these filters', alarmReadError: 'Alarm review unavailable; retained rows may be outdated.', recordedUser: 'Recorded user',
  legacyIdentity: 'Not recorded (legacy)', acknowledgementNotRequired: 'Not required (automatic)', monitorEvent: 'Monitor',
  alarmAckPending: 'Acknowledged; activity finalization pending. Operation {id}', alarmNotePending: 'Note saved; activity finalization pending. Operation {id}',
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
