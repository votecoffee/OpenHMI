import { api, json } from './api.mjs';

const rules = [
  ['.openhmi.hold', 'connection_hold'], ['.openhmi.handlers.py', 'python_review'],
  ['.openhmi.recipe-users.json', 'recipe_accounts'], ['.openhmi.sqlite3-wal', 'sqlite_wal'],
  ['.openhmi.sqlite3-shm', 'sqlite_shm'], ['.openhmi.sqlite3-journal', 'sqlite_journal'],
];
const entryTypes = ['file', 'directory', 'link', 'other', 'unavailable'];
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const filename = (value, maximum = 255) => typeof value === 'string' && [...value].length > 0
  && [...value].length <= maximum && !/[\\/\x00]/.test(value);

// Match Python's Unicode code-point order, including non-BMP filenames.
function compareNames(left, right) {
  const a = [...left].map(char => char.codePointAt(0)), b = [...right].map(char => char.codePointAt(0));
  for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) return a[i] - b[i];
  return a.length - b.length;
}

export function workspaceArtifactPath({ after = '', limit = null } = {}) {
  const params = new URLSearchParams();
  if (after) params.set('after', after);
  if (limit != null) params.set('limit', String(limit));
  return '/api/workspace/artifacts' + (params.size ? '?' + params : '');
}

export function isWorkspaceArtifactPage(page, after = '') {
  if (!record(page) || !Array.isArray(page.items) || page.items.length > 100 || typeof page.scan_limited !== 'boolean'
    || !(page.next_after === null || filename(page.next_after))
    || (page.next_after !== null && (!page.items.length || page.next_after !== page.items.at(-1)?.file))) return false;
  let previous = after;
  return page.items.every(item => {
    if (!record(item) || !filename(item.file) || !filename(item.project_file, 512)
      || compareNames(item.file, previous) <= 0 || !entryTypes.includes(item.entry_type)
      || ![...entryTypes, 'missing'].includes(item.project_entry_type)
      || !(item.size_bytes === null || (Number.isSafeInteger(item.size_bytes) && item.size_bytes >= 0))
      || (item.entry_type !== 'file' && item.size_bytes !== null)) return false;
    const rule = rules.find(([suffix]) => item.file.endsWith(suffix) && item.file.length > suffix.length);
    if (!rule || item.kind !== rule[1] || item.project_file !== item.file.slice(0, -rule[0].length) + '.openhmi.sqlite3') return false;
    previous = item.file;
    return true;
  });
}

export async function readWorkspaceArtifacts(options = {}) {
  const page = await api(workspaceArtifactPath(options));
  if (!isWorkspaceArtifactPage(page, options.after ?? '')) throw new Error('Project file inventory response is invalid');
  return page;
}


export function isWorkspaceLibrary(data) {
  if (!record(data) || !filename(data.current) || !Array.isArray(data.projects) || !data.projects.length
    || typeof data.handlers !== 'boolean' || typeof data.plc_hold !== 'boolean') return false;
  const names = new Set(), active = [];
  for (const project of data.projects) {
    if (!record(project) || !filename(project.file) || names.has(project.file) || typeof project.current !== 'boolean') return false;
    names.add(project.file);
    if (project.current) active.push(project.file);
  }
  return active.length === 1 && active[0] === data.current;
}

export function isWorkspaceResult(data, kind, expectedFile) {
  if (!record(data)) return false;
  if (kind === 'open') return data.ok === true && filename(data.current) && data.current === expectedFile;
  if (!['create', 'import'].includes(kind) || !filename(data.file)
    || !/^[A-Za-z][A-Za-z0-9_-]{0,59}\.openhmi\.sqlite3$/.test(data.file) || data.file !== expectedFile) return false;
  return kind === 'create' || (data.plc_hold === true && typeof data.handlers_saved_for_review === 'boolean');
}

export async function readWorkspaceLibrary() {
  const data = await api('/api/workspace');
  if (!isWorkspaceLibrary(data)) throw new Error('Project library response is invalid');
  return data;
}

async function workspaceOperation(kind, expectedFile, path, options) {
  let data;
  try { data = await api(path, options); }
  catch (error) {
    if (!Number.isInteger(error.status) || error.status >= 500) {
      error.requiresReview = true;
      error.message += '. The operation may have completed. Refresh the project library before trying again.';
    }
    throw error;
  }
  if (!isWorkspaceResult(data, kind, expectedFile)) {
    const error = new Error('Project operation response is invalid. The operation may have completed. Refresh the project library before trying again.');
    error.requiresReview = true;
    throw error;
  }
  return data;
}

export function createWorkspaceProject(name, title) {
  return workspaceOperation('create', name + '.openhmi.sqlite3', '/api/workspace/create', json('POST', { name, title }));
}

export function openWorkspaceProject(file) {
  return workspaceOperation('open', file, '/api/workspace/open', json('POST', { file }));
}

export function importWorkspaceProject(name, file) {
  return workspaceOperation('import', name + '.openhmi.sqlite3', '/api/workspace/import?' + new URLSearchParams({ name }),
    { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file });
}
