import { isOccurrencePage, isEventPage, isNotePage, isAlarmDetail } from '../frontend/alarm-responses.mjs';
import { isRecipeSelection, recipeSelectionPath } from '../frontend/recipe-selection.mjs';
import { requireIdentitySnapshot, readSecuritySession } from '../frontend/security-session.mjs';
import { activityOutcomes, isActivityPage, readActivity, activityCsvPath } from '../frontend/activity-api.mjs';
import { isDiagnosticsSnapshot, readDiagnostics, diagnosticsExportPath } from '../frontend/diagnostics-api.mjs';
// Exercise production palette defaults and serializers without a DOM or PLC.
import { createConfig } from '../frontend/controls.jsx';
import { controlTypes, toEditor, toProject, scopedScreen } from '../frontend/model.mjs';
import { resolveFaceplateControl } from '../frontend/faceplate-model.mjs';
import { api, uploadProjectImage } from '../frontend/api.mjs';
import { readLatestCommand, commandHistoryPath, commandTransactionPath } from '../frontend/command-api.mjs';
import { commandStates, isCommandRecord, isCommandPage } from '../frontend/command-status.mjs';
import { listProjectImages, isProjectImagePage } from '../frontend/image-api.mjs';
import { sparklineHistoryPath, trendReadPaths, recordedHistoryTags, historyExportPath, fetchHistoryCsv, isRecordedTagPage, isTrendHistory } from '../frontend/history-api.mjs';
import { isCaptureStatus, captureCsvPath } from '../frontend/trend-api.mjs';
import { sendCaptureCommand } from '../frontend/trend-api.mjs';
import { publicationStatus, claimPublicationStation, releasePublicationStation } from '../frontend/identity-api.mjs';
import { writeControlValue, activateControl, renewSubscription, requireTagSnapshot, tagSnapshotPath } from '../frontend/runtime-api.mjs';
import { saveProjectDraft, applyLiveProject, isAppliedProjectSnapshot, appliedProjectPath } from '../frontend/project-api.mjs';
import { acknowledgeAlarms, isAlarmSnapshot, alarmSnapshotPath, alarmOccurrencesPath, alarmEventsPath, alarmDetailPath, alarmNotesPath, alarmEventsCsvPath, alarmStates, alarmShelvingFilters, alarmEvents, saveAlarmNote, shelveAlarm, restoreAlarm } from '../frontend/alarm-api.mjs';
import { engineeringCatalog } from '../frontend/engineering.jsx';
import { createPaletteFields } from '../frontend/palette-fields.jsx';
import { paletteFactories } from '../frontend/palette-components.jsx';

export async function contract(request) {
  if (request.operation === 'alarm_responses') {
    const before = JSON.stringify(request);
    const result = { occurrences: request.occurrences.map(isOccurrencePage), events: request.events.map(isEventPage),
      notes: request.notes.map(isNotePage), details: request.details.map(item => isAlarmDetail(item.data, item.identifier)) };
    if (JSON.stringify(request) !== before) throw new Error('Alarm response validation mutated input');
    return result;
  }

  if (request.operation === 'alarm_queries') return {
    states: alarmStates, shelving: alarmShelvingFilters, events: alarmEvents,
    occurrences: request.occurrences.map(item => alarmOccurrencesPath(item.filters, item.before, item.options)),
    history: request.history.map(item => alarmEventsPath(item.filters, item.before, item.event, item.options)),
    csv: request.history.map(item => alarmEventsCsvPath(item.filters, item.event)),
    details: request.details.map(alarmDetailPath),
    notes: request.notes.map(item => alarmNotesPath(item.identifier, item.before, item.options)),
  };

  if (request.operation === 'tag_snapshots') {
    const before = JSON.stringify(request.snapshots);
    const results = request.snapshots.map(({ data, statusOnly = false }) => {
      try { return { valid: true, normalized: requireTagSnapshot(data, statusOnly) }; }
      catch (error) { return { valid: false, error: error.message }; }
    });
    if (JSON.stringify(request.snapshots) !== before) throw new Error('Tag validation mutated input');
    return { paths: [tagSnapshotPath(), tagSnapshotPath(true)], results };
  }

  if (request.operation === 'applied_projects') {
    const before = JSON.stringify(request.snapshots);
    const valid = request.snapshots.map(isAppliedProjectSnapshot);
    if (JSON.stringify(request.snapshots) !== before) throw new Error('Project validation mutated input');
    return { path: appliedProjectPath, valid };
  }

  if (request.operation === 'alarm_snapshots') {
    const before = JSON.stringify(request.snapshots);
    const valid = request.snapshots.map(isAlarmSnapshot);
    if (JSON.stringify(request.snapshots) !== before) throw new Error('Alarm validation mutated input');
    return { path: alarmSnapshotPath, valid };
  }

  if (request.operation === 'recipe_selections') {
    const before = JSON.stringify(request.selections);
    const valid = request.selections.map(isRecipeSelection);
    if (JSON.stringify(request.selections) !== before) throw new Error('Recipe validation mutated input');
    return { path: recipeSelectionPath, valid };
  }

  if (request.operation === 'security_sessions') {
    const before = JSON.stringify(request.sessions);
    const valid = request.sessions.map(value => {
      try { return requireIdentitySnapshot(value) === value; } catch { return false; }
    });
    if (JSON.stringify(request.sessions) !== before) throw new Error('Session validation mutated input');
    return valid;
  }
  if (request.operation === 'security_session_read') {
    const requests = [];
    globalThis.fetch = async (path, options) => {
      requests.push({ path, headers: options.headers, timed: options.signal instanceof AbortSignal, method: options.method ?? 'GET' });
      return new Response(JSON.stringify(request.response), { status: request.status ?? 200,
        headers: { 'Content-Type': 'application/json' } });
    };
    try { return { requests, identity: await readSecuritySession() }; }
    catch (error) { return { requests, error: error.message, status: error.status ?? null }; }
  }

  if (request.operation === 'operations_responses') return { outcomes: activityOutcomes, pages: request.pages.map(isActivityPage), snapshots: request.snapshots.map(item => isDiagnosticsSnapshot(item.data, item.offset)) };
  if (request.operation === 'trend_responses') return { histories: request.histories.map(isTrendHistory), statuses: request.statuses.map(isCaptureStatus) };
  if (request.operation === 'command_responses') return { states: commandStates, records: request.records.map(isCommandRecord), pages: request.pages.map(isCommandPage) };
  if (request.operation === 'recorded_pages') return request.pages.map(isRecordedTagPage);
  if (request.operation === 'image_pages') return request.pages.map(isProjectImagePage);
  if (request.operation === 'engineering') {
    const catalog = engineeringCatalog(request.catalog, request.project, request.template ?? null);
    const config = createConfig(catalog);
    return { catalog, modeTags: config.components.ModeSelector.fields.tag.options,
      sliderTags: config.components.Slider.fields.tag.options,
      components: Object.keys(config.components) };
  }
  if (request.operation === 'catalogs') {
    const first = createConfig(request.catalogs[0]);
    first.components.NumericInput.fields.tag.options.push({ label: 'Poison', value: 'Poison' });
    first.components.MultiState.defaultProps.states[0].label = 'Mutated';
    return request.catalogs.map(catalog => {
      const config = createConfig(catalog);
      return {
        dropdown: config.components.Dropdown.defaultProps,
        slider: config.components.Slider.defaultProps,
        numericTags: config.components.NumericInput.fields.tag.options,
        sliderTags: config.components.Slider.fields.tag.options,
        modeTags: config.components.ModeSelector.fields.tag.options,
        states: config.components.MultiState.defaultProps.states,
      };
    });
  }
  if (request.operation === 'defaults') {
    const config = createConfig(request.catalog);
    const content = Object.entries(config.components).map(([type, component]) => ({
      type, props: { ...component.defaultProps, ...request.bindings?.[type], id: 'contract_' + type },
    }));
    const editor = { root: { props: config.root.defaultProps }, content };
    const selections = content.flatMap(item => Object.entries(config.components[item.type].fields)
      .filter(([, field]) => field.type === 'select')
      .flatMap(([name, field]) => field.options.filter(option => option.value !== '').map(option => ({
        component: item.type, field: name, value: option.value,
        control: toProject({ ...editor, content: [{ ...item, props: { ...item.props, [name]: option.value } }] }).controls[0],
      }))));
    const fields = createPaletteFields(request.catalog);
    const families = paletteFactories.map(factory => Object.keys(factory(request.catalog, fields, () => config)));
    return { types: controlTypes, components: Object.keys(config.components), inputTypes: config.categories.inputs.components,
      families, categories: Object.values(config.categories).map(category => category.components),
      project: toProject(editor), selections };
  }
  if (request.operation === 'roundtrip') {
    return request.projects.map(project => toProject(toEditor(project), project));
  }
  if (request.operation === 'faceplates') {
    const original = JSON.stringify(request.project);
    const screen = scopedScreen(request.project, request.screen);
    const controls = screen.controls.flatMap(instance => {
      const template = request.project.faceplates.find(item => item.id === instance.template);
      return template.controls.map(control => resolveFaceplateControl(control, instance));
    });
    if (JSON.stringify(request.project) !== original) throw new Error('Faceplate resolution mutated the project');
    return controls;
  }
  if (request.operation === 'requests' || request.operation === 'lifecycle_requests' || request.operation === 'service_requests' || request.operation === 'command_queries' || request.operation === 'image_queries' || request.operation === 'history_queries' || request.operation === 'operations_queries' || request.operation === 'alarm_mutations') {
    const requests = [];
    globalThis.fetch = async (path, options) => {
      const upload = options.body instanceof Blob;
      requests.push({ path, method: options.method, headers: options.headers,
        keepalive: options.keepalive, timed: options.signal instanceof AbortSignal, body: upload ? null : options.body && JSON.parse(options.body),
        ...(upload ? { upload: { name: options.body.name, type: options.body.type, bytes: Array.from(new Uint8Array(await options.body.arrayBuffer())) },
          timeout: options.signal instanceof AbortSignal } : {}) });
      const mutation = request.operation === 'alarm_mutations' && path !== '/api/project';
      const status = mutation ? request.status ?? 200 : 200;
      return new Response(JSON.stringify(status >= 400 ? { detail: 'Synthetic denial' } : { ok: true, project_instance: 'a'.repeat(32) }), {
        status, headers: { 'Content-Type': 'application/json', ...(mutation ? {
          'X-OpenHMI-Operation-ID': 'b'.repeat(32), 'X-OpenHMI-Audit-Status': status >= 400 ? 'denied' : 'pending' } : {}) },
      });
    };
    await api('/api/project');
    if (request.operation === 'alarm_mutations') {
      const results = [];
      for (const item of request.mutations) {
        try {
          results.push(item.action === 'note' ? await saveAlarmNote(item.id, item.comment)
            : item.action === 'shelve' ? await shelveAlarm(item.id, item.duration, item.reason)
            : await restoreAlarm(item.id, item.expected, item.reason));
        } catch (error) { results.push({ error: error.message, status: error.status, operation_id: error.operation_id, audit_status: error.audit_status }); }
      }
      return { requests: requests.slice(1), results };
    }
    if (request.operation === 'operations_queries') {
      for (const item of request.activity) await readActivity(item.filters, item.before, item.options);
      for (const item of request.diagnostics) await readDiagnostics(item.criteria, item.offset, item.options);
      return { requests: requests.slice(1), csv: request.activity.map(item => activityCsvPath(item.filters)),
        exports: request.diagnostics.map(item => diagnosticsExportPath(item.criteria)), outcomes: activityOutcomes };
    }
    if (request.operation === 'history_queries') {
      const tags = '设备 A,Motor.Speed,设备 A';
      await api(sparklineHistoryPath('设备 A', 10));
      await api(trendReadPaths({ tags, seconds: 60 }).query);
      const fixed = trendReadPaths({ tags: 'Motor.Speed', seconds: 30, end: 1700000000.125 });
      await api(fixed.query);
      await api(trendReadPaths({ tags: 'Motor.Speed', seconds: 10, end: 0 }).query);
      await api(trendReadPaths({ tags: 'ignored', seconds: 10, end: 1700000000.125, captureId: '9223372036854775807' }).query);
      await fetchHistoryCsv(fixed.csv);
      await fetchHistoryCsv(historyExportPath({ tags, seconds: 3600, end: 1700000000.125 }));
      await api(historyExportPath({ tags, start: 0, end: 31536000, complete: true, projectInstance: 'a'.repeat(32) }));
      await recordedHistoryTags({ prefix: '设备 ', after: '设备 A', limit: 100, projectInstance: 'a'.repeat(32) });
      await recordedHistoryTags({ projectInstance: 'a'.repeat(32) });
      await api(captureCsvPath(123));
      return { requests: requests.slice(1), empty: trendReadPaths({ tags: '', seconds: 10 }) };
    }
    if (request.operation === 'image_queries') {
      await listProjectImages();
      await listProjectImages({ before: 42 });
      await listProjectImages({ search: '设备 / %.png?#' });
      await listProjectImages({ before: '9223372036854775807', search: '设备 / %.png?#', limit: 32 });
      await listProjectImages({ limit: 1 });
      await listProjectImages({ search: 'x'.repeat(100) });
      return requests.slice(1);
    }
    if (request.operation === 'command_queries') {
      await readLatestCommand('设备 / Cycle?#');
      await api(commandHistoryPath());
      await api(commandHistoryPath({ limit: 200, command: '设备 / Cycle?#', state: 'unresolved', before: '9223372036854775807' }));
      for (const state of ['unresolved', ...commandStates]) await api(commandHistoryPath({ state }));
      await api(commandTransactionPath(123));
      await api(commandTransactionPath('9223372036854775807', true));
      return { requests: requests.slice(1), states: ['', 'unresolved', ...commandStates] };
    }
    if (request.operation === 'service_requests') {
      for (const [action, captureId] of [['start', 0], ['stop', 123], ['delete', 123]]) {
        await sendCaptureCommand('设备 / trend?#', action, captureId);
      }
      await publicationStatus();
      await claimPublicationStation('station 设备');
      await claimPublicationStation('station 设备', true);
      await releasePublicationStation('station 设备');
      await uploadProjectImage(new File([new Uint8Array([137, 80, 78, 71])], '机器 pic #.png', { type: 'image/png' }));
      return requests.slice(1);
    }
    if (request.operation === 'lifecycle_requests') {
      await saveProjectDraft(request.project, 123);
      await applyLiveProject(123, '  更改画面  ');
      await applyLiveProject(124, '  ');
      await acknowledgeAlarms(1, '已检查');
      await acknowledgeAlarms(null, 'All inspected');
      await acknowledgeAlarms(null, 'Selected inspected', [2, 3]);
      return requests.slice(1);
    }
    for (const value of [0, 0.25, false, true, '001 设备', '']) {
      await writeControlValue('details__motor__speed', value, 123);
    }
    await activateControl('details__motor__start', 123);
    await renewSubscription('contract-viewer', ['overview', 'details'], 'MotorA', 42);
    await renewSubscription('contract-viewer', [], '', 43, true);
    return requests.slice(1);
  }
  throw new Error('Unknown frontend contract operation');
}
