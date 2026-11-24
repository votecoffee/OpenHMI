import { readRuntimeSnapshot } from './api.mjs';

export function readLatestCommand(command) {
  return readRuntimeSnapshot(`/api/commands?command_id=${encodeURIComponent(command)}&limit=1`);
}

export function commandHistoryPath({ limit = 50, command = '', state = '', before = null } = {}) {
  const parameters = new URLSearchParams({ limit: String(limit) });
  if (command) parameters.set('command_id', command);
  if (state) parameters.set('state', state);
  if (before) parameters.set('before_id', before);
  return `/api/commands?${parameters}`;
}

export function commandTransactionPath(identifier, download = false) {
  return `/api/commands/${identifier}` + (download ? '?download=true' : '');
}
