import React, { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';

export const uiText = {
  viewCommandTransaction: 'View command transaction #{id}',
  commandStatusWaiting: 'Waiting for command status', commandStatusUnavailable: 'Command status unavailable',
  languageSelector: 'Language: {name}', configuredLanguages: 'Configured languages',
  canvasDisplay: 'Canvas display', canvasActualSize: 'Actual size', canvasFitWidth: 'Fit width', canvasDisplayScale: '{percent}% scale',
  clearTrendCursor: 'Clear trend cursor',
  trendTimeline: '{label} timeline. Use left and right arrows to move the cursor.',
  trendPlot: '{label} trend', trendBooleanHistory: '{tag} Boolean history', trendAnalog: 'Analog',
  trendEnd: 'End', trendNow: 'Now', trendLive: 'Live', trendLatest: 'Latest',
  trendHours: '{count} h', trendMinutes: '{count} min', trendSeconds: '{count} s',
  trendTimeRange: 'Time range', trendTimeRangeLabel: '{label} time range',
  trendWindowSeconds: 'Window (seconds)', trendWindowLabel: '{label} window seconds',
  trendEndTime: 'End time', trendEndLabel: '{label} history end', trendCursor: 'Cursor: {time}',
  trendTag: 'Tag', trendCurrent: 'Current (live)', trendAtCursor: 'At cursor', trendYAxisRange: 'Y-axis range',
  trendRange: '{low} to {high}', trendFixed: 'Fixed', trendObserved: 'Observed',
  trendInvalidRange: 'Invalid range', trendWaiting: 'Waiting for samples',
  trendHistoryUnavailable: 'History unavailable', trendLastHistory: 'Showing last received history ending {time}',
  trendSelectTags: 'Select trend tags.',
  trendNoSamples: 'No recorded good samples in this window. Check acquisition settings and tag quality.',
  trendLimited: 'Result limited. Shorten the time range.',
  trendOnChangeHint: 'On-change traces hold the last recorded value between samples.',
  trendExportHistory: 'Export history CSV', trendData: 'Trend data',
  trendAutoSource: 'Latest capture (or historian)', trendHistorySource: 'Continuous historian',
  trendCaptureOption: '#{id} {time}', trendRun: 'Run trend', trendStop: 'Stop trend',
  trendRecording: 'Recording #{id}', trendArmed: 'Armed for start trigger', trendStopped: 'Stopped',
  trendRecordingUnavailable: 'Recording status unavailable', trendRecordingWaiting: 'Waiting for recording status',
  trendLastRecordingStatus: 'Showing last received recording status',
  trendRetention: 'Capture #{id} · {retained} / {max} samples retained', trendRolledOff: '{count} rolled off',
  trendCapturePosition: 'Capture position', trendExportCapture: 'Export entire capture CSV',
  trendDeleteCapture: 'Delete saved capture', trendConfirmDelete: 'Confirm delete capture',
  trendManualStop: 'manual stop', trendStopTrigger: 'stop trigger', trendRuntimeStopped: 'runtime stopped',
  trendConfigurationChanged: 'configuration changed', trendInterrupted: 'interrupted',
  closeDialog: 'Close {title}', closePopup: 'Close popup', entryLabel: 'Entry', passwordEntry: 'Password entry', numericKeypad: 'Numeric keypad',
  textKeyboard: 'Text keyboard', shiftKey: 'Shift', spaceKey: 'Space', backspaceKey: 'Backspace', clearEntry: 'Clear',
  cancelEntry: 'Cancel', acceptEntry: 'Accept entry', invalidNumericEntry: 'Enter a finite number',
  allowedNumericRange: 'Allowed range: {low} to {high}', allowedTextLength: 'Allowed length: {low} to {high}',
  numericRange: 'Range: {low} – {high}', textLength: 'Length: {low} – {high}', editLimitsUnavailable: 'Edit limits unavailable',
  editLimitsInvalid: 'Edit limits are invalid', editMinimum: 'Minimum', editMaximum: 'Maximum',
  editMinLength: 'Minimum length', editMaxLength: 'Maximum length', editEnableBinding: 'Enable tag',
  editBindingProblem: '{binding} · {quality}', editEnableOff: 'Enable tag {tag} is off',
  editNamedBindingProblem: '{binding} {tag} · {quality}', editValueBinding: 'Value tag',
  editInstanceEnableBinding: 'Faceplate enable tag', editNotAuthorized: 'Your current HMI permissions do not allow this edit',
  actionPermitBinding: 'PLC permit', actionPermitOff: 'PLC permit {tag} is off',
  actionCommandBinding: 'Command channel', actionTargetBinding: 'Target tag',
  editOutsideLimits: 'Entry is outside the current edit limits', enterValue: 'Enter a value',
  editRevisionChanged: 'The applied project changed. Reopen the keypad or clear and re-enter the value.',
  newControlValue: '{label} new value', writeValue: 'Write value', valueWritten: 'Value written',
  valueWritePending: 'Value written; activity finalization pending. Operation {id}',
  openTextKeyboard: 'Open keyboard for {label}', openNumericKeypad: 'Open numeric keypad for {label}',
  textEntryTitle: 'Text entry: {label}', numericEntryTitle: 'Numeric entry: {label}',
  hmiLogin: 'HMI login', openHmiLogin: 'Open HMI login', hmiUser: 'HMI user', hmiPassword: 'HMI password',
  loginAccountType: 'Account type', localHmiAccount: 'Local HMI account', windowsAccount: 'Windows account',
  userKeyboard: 'User keyboard', passwordKeyboard: 'Password keyboard', signInHmi: 'Sign in to HMI',
  signOutHmi: 'Sign out of HMI', hmiSignedOut: 'Signed out', hmiSignedIn: 'Signed in:',
  loginStatusUnavailable: 'Login status unavailable — controls are locked.',
  alarmShelving: 'Alarm shelving', shelfExplanation: 'Shelving applies to this alarm and its retriggers until expiry. Monitoring and history continue. Global counts and Acknowledge all include shelved alarms. This registry is independent of list filters.',
  shelfReason: 'Reason for shelving or restoring', shelfDuration: 'Shelf duration', shelfMinutes: '{count} minutes', shelfExpiry: 'Shelved until',
  shelfFilter: 'Shelving filter', unshelved: 'Unshelved', shelved: 'Shelved', allShelving: 'All shelving states',
  noShelves: 'No active shelves on this page', firstShelves: 'First shelves', moreShelves: 'More shelves', shelveAlarm: 'Shelve this alarm',
  restoreAlarm: 'Restore alarm', restoreAlarmNamed: 'Restore {name}', shelfSaved: 'Alarm shelved', shelfRestored: 'Alarm restored',
  shelf_restored: 'Shelf restored', shelf_expired: 'Shelf expired', shelf_invalidated: 'Shelf invalidated by configuration',
  shelvedSummary: 'Shelved alarm definitions: {count}', noUnshelvedAlarms: 'No unshelved outstanding alarms', shelfPending: 'Shelf operation completed; activity finalization pending. Operation {id}',
  simulation: 'SIMULATION', localStation: 'LOCAL STATION', dataConnected: 'Data connected', commLoss: 'COMM LOSS',
  simulatorOnline: 'Simulator connected', simulatorOffline: 'Simulator disconnected',
  runtimeOnline: 'Runtime connected', runtimeOffline: 'Runtime offline',
  plcOnline: 'PLC routes connected ({connected}/{total})', plcPartial: 'PLC partial outage ({connected}/{total} connected)',
  plcOffline: 'PLC communication lost', plcConnecting: 'Connecting to PLC', plcDisabled: 'PLC routes disabled',
  plcHeld: 'PLC acquisition held', routeConnected: 'Connected', routeConnecting: 'Connecting',
  routeRetrying: 'Disconnected / retrying', routeUnknown: 'Status unavailable', routeHeld: 'Held', routeDisabled: 'Disabled',
  tagHeld: 'ACQUISITION HELD', tagDisabled: 'ROUTE DISABLED', tagPlcOffline: 'PLC COMM LOSS',
  tagRecovering: 'WAITING FOR FRESH DATA', tagWaiting: 'WAITING FOR DATA', tagStale: 'STALE DATA', tagUnavailable: 'DATA UNAVAILABLE', tagGood: 'Good data',
  cameraRefresh: 'Refresh camera', cameraOpenTab: 'Open camera in new tab',
  cameraDesigner: 'Configure the approved endpoint here. Open the live screen to view it.',
  cameraAddressBlocked: 'CAMERA ADDRESS MISSING OR BLOCKED',
  cameraOpening: 'Opening embedded page. If it stays blank, use the new tab.',
  cameraUnverified: 'Camera health unverified. If the view is blank, use the new tab.',
  cameraMixedContent: 'HTTP camera embedding is blocked on an HTTPS station. Use the new tab.',
  cameraIsolationUnavailable: 'This browser cannot isolate the embedded camera. Use the new tab.',
  tagInspectQuality: 'Inspect {tag} quality ({label})', tagQualityDetails: 'Tag quality details',
  tagQualityBinding: 'Tag', tagQualityReason: 'Reason', tagSourceTime: 'Source time', tagAge: 'Sample age',
  tagSampleAge: '{age} s old', editDataUnavailable: 'Fresh data and an enabled control are required to write',
  badData: 'BAD DATA', badRange: 'BAD RANGE', on: 'ON', off: 'OFF', state: 'STATE', textShape: 'Text + shape',
  inactive: 'INACTIVE', active: 'ACTIVE', normal: 'Normal', outOfScale: 'OUT OF SCALE', outsideBand: 'OUTSIDE NORMAL BAND',
  overview: 'OVERVIEW', localSimulator: 'LOCAL SIMULATOR', localPlcRuntime: 'LOCAL PLC RUNTIME', preview: 'PREVIEW', editScreen: 'EDIT SCREEN',
  alarmUnavailable: 'ALARM MONITOR UNAVAILABLE', noAlarms: 'No alarms configured', noActiveAlarms: 'No active or unacknowledged alarms',
  alarmEvaluationWaiting: 'Waiting for alarm evaluation', alarmEvaluationStale: 'Alarm evaluation is stale',
  lastRecordedAlarmCounts: 'Last recorded: {active} active / {unack} unacknowledged',
  alarmUnavailableTriggers: 'Unavailable alarm triggers', alarmUnavailableTriggersCount: 'Unavailable alarm triggers ({count})',
  alarmUnavailableTriggersHint: 'These alarms cannot be evaluated with the current trigger data.',
  noRecordedAlarmsInView: 'No recorded alarms in this view',
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
  alarmDetails: 'Alarm details', openAlarmDetails: 'Alarm details: {message}', inspectAlarm: 'Details {id}', triggerQuality: 'Current trigger quality', possibleCause: 'Possible cause', operatorResponse: 'Recovery steps',
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
const format = (value, params = {}) => value.replace(/\{(\w+)\}/g, (match, name) =>
  Object.hasOwn(params, name) ? String(params[name]) : match);
const defaultUi = (key, params) => format(uiText[key] ?? key, params);

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
    return format(value, params);
  }
  return <Context.Provider value={{ language, languages, choose, text, ui: (key, params) => text(`ui.${key}`, uiText[key], params) }}>{children}</Context.Provider>;
}

export function useLocalization() { return useContext(Context); }
export function useUi() { return useContext(Context)?.ui ?? defaultUi; }

export function formatLocalDateTime(date, code, options) {
  try { return date.toLocaleString(code, options); }
  catch { return date.toLocaleString(undefined, options); }
}

export function LanguageSelector() {
  const { language, languages, choose, ui } = useLocalization();
  const [index, setIndex] = useState(null);
  const selector = useRef(null);
  const trigger = useRef(null);
  const menu = useRef(null);
  const menuId = useId();
  const others = languages.filter(item => item.code !== language.code);
  const last = others.length - 1;
  const active = index === null || last < 0 ? null : Math.min(index, last);
  const activeCode = active === null ? null : others[active].code;
  const open = active !== null;
  useLayoutEffect(() => {
    if (active !== null) menu.current.children[active]?.focus();
    else if (index !== null) setIndex(null);
  }, [active, activeCode, index]);
  useEffect(() => {
    if (!open) return;
    function dismiss(event) {
      if (!selector.current?.contains(event.target)) setIndex(null);
    }
    document.addEventListener('pointerdown', dismiss, true);
    return () => document.removeEventListener('pointerdown', dismiss, true);
  }, [open]);
  function close() {
    setIndex(null);
    trigger.current.focus();
  }
  function key(event) {
    if (open && event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (open && event.key === 'Tab') {
      close();
      return;
    }
    let next;
    switch (event.key) {
      case 'ArrowDown': next = active === null || active === last ? 0 : active + 1; break;
      case 'ArrowUp': next = active === null || active === 0 ? last : active - 1; break;
      case 'Home': if (open) next = 0; break;
      case 'End': if (open) next = last; break;
      default: break;
    }
    if (next === undefined || last < 0) return;
    event.preventDefault();
    setIndex(next);
  }
  return <div ref={selector} className="language-selector" onKeyDown={key} onBlur={event => {
    if (open && !event.currentTarget.contains(event.relatedTarget)) setIndex(null);
  }}>
    <button ref={trigger} type="button" className="language-button" aria-label={ui('languageSelector', { name: language.name })}
      aria-expanded={open} aria-haspopup="menu" aria-controls={open ? menuId : undefined}
      disabled={last < 0} onClick={() => open ? close() : setIndex(0)}>
      <img src={`/static/assets/flags/${language.flag}.svg`} alt={language.name} /><span aria-hidden="true">▾</span>
    </button>
    {open && <div ref={menu} id={menuId} className="language-menu" role="menu" aria-label={ui('configuredLanguages')}>
      {others.map(item => <button key={item.code} type="button" role="menuitem" tabIndex={-1} lang={item.code}
        onClick={() => { choose(item.code); close(); }}>
        <img src={`/static/assets/flags/${item.flag}.svg`} alt="" /><span>{item.name}</span>
      </button>)}
    </div>}
  </div>;
}

export function alarmMessage(alarm, language) { return alarm.messages?.[language.code] || alarm.message; }
