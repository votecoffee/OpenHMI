import { projectRequestHeaders } from './api.mjs';

export const MAX_BACKUP_BYTES = 256 * 1024 * 1024;
const allowedNames = new Set(['manifest.json', 'project.sqlite3', 'handlers.py', 'recipe-users.json']);
const decoder = new TextDecoder('utf-8', { fatal: true });

// Validate bounded ZIP framing only. Import owns manifest/checksum/SQL validation.
export async function isCompleteBackupZip(blob) {
  try {
    if (!(blob instanceof Blob) || blob.size < 22 || blob.size > MAX_BACKUP_BYTES) return false;
    const prefix = new DataView(await blob.slice(0, 4).arrayBuffer());
    if (prefix.getUint32(0, true) !== 0x04034b50) return false;
    const tailStart = Math.max(0, blob.size - 65557);
    const tail = new DataView(await blob.slice(tailStart).arrayBuffer());
    let end = -1;
    for (let i = tail.byteLength - 22; i >= 0; i--) {
      if (tail.getUint32(i, true) === 0x06054b50 && i + 22 + tail.getUint16(i + 20, true) === tail.byteLength) { end = i; break; }
    }
    if (end < 0 || tail.getUint16(end + 4, true) || tail.getUint16(end + 6, true)) return false;
    const count = tail.getUint16(end + 10, true), size = tail.getUint32(end + 12, true), offset = tail.getUint32(end + 16, true);
    if (count < 2 || count > 4 || count !== tail.getUint16(end + 8, true) || size > 4096 || offset + size !== tailStart + end) return false;
    const central = new DataView(await blob.slice(offset, offset + size).arrayBuffer());
    const names = new Set(), spans = [];
    let cursor = 0, unpacked = 0;
    for (let i = 0; i < count; i++) {
      if (central.getUint32(cursor, true) !== 0x02014b50) return false;
      const flags = central.getUint16(cursor + 8, true), method = central.getUint16(cursor + 10, true);
      const packed = central.getUint32(cursor + 20, true), raw = central.getUint32(cursor + 24, true);
      const nameSize = central.getUint16(cursor + 28, true), extra = central.getUint16(cursor + 30, true), comment = central.getUint16(cursor + 32, true);
      const localOffset = central.getUint32(cursor + 42, true);
      if ((flags & 1) || ![0, 8].includes(method) || central.getUint16(cursor + 34, true) || nameSize > 100) return false;
      const name = decoder.decode(new Uint8Array(central.buffer, cursor + 46, nameSize));
      if (!allowedNames.has(name) || names.has(name)) return false;
      names.add(name); unpacked += raw;
      if (unpacked > MAX_BACKUP_BYTES || localOffset >= offset) return false;
      const local = new DataView(await blob.slice(localOffset, localOffset + 30 + nameSize).arrayBuffer());
      if (local.getUint32(0, true) !== 0x04034b50 || local.getUint16(6, true) !== flags || local.getUint16(8, true) !== method
        || local.getUint16(26, true) !== nameSize || decoder.decode(new Uint8Array(local.buffer, 30, nameSize)) !== name) return false;
      const dataEnd = localOffset + 30 + nameSize + local.getUint16(28, true) + packed;
      if (dataEnd > offset) return false;
      if (!(flags & 8) && (local.getUint32(14, true) !== central.getUint32(cursor + 16, true)
        || local.getUint32(18, true) !== packed || local.getUint32(22, true) !== raw)) return false;
      spans.push([localOffset, dataEnd]);
      cursor += 46 + nameSize + extra + comment;
    }
    spans.sort((a, b) => a[0] - b[0]);
    return cursor === size && names.has('manifest.json') && names.has('project.sqlite3')
      && spans.every((span, i) => i === 0 || span[0] >= spans[i - 1][1]);
  } catch { return false; }
}

async function boundedBody(response, maximum) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Backup response body is unavailable');
  let total = 0;
  const chunks = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maximum) throw new Error('Backup response exceeds the download limit');
      chunks.push(value);
    }
    return new Blob(chunks, { type: 'application/zip' });
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
}

export async function fetchWorkspaceBackup() {
  const headers = projectRequestHeaders();
  let response;
  try { response = await fetch('/api/workspace/backup', { method: 'GET', headers, cache: 'no-store', signal: AbortSignal.timeout(30000) }); }
  catch (error) { throw new Error(`Complete backup download failed: ${error.message}`); }
  try {
    if (!response.ok) {
      let detail;
      try { detail = JSON.parse(await (await boundedBody(response, 8192)).text()).detail; } catch {}
      const error = new Error(typeof detail === 'string' && detail ? detail : `Backup export failed (HTTP ${response.status})`);
      error.status = response.status; error.requiresReview = response.status === 409;
      throw error;
    }
    if (response.status !== 200 || response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/zip'
      || !/^attachment;\s*filename=(?:"project\.openhmi\.zip"|project\.openhmi\.zip)$/i.test(response.headers.get('Content-Disposition')?.trim() ?? '')) {
      throw new Error('Server did not return a complete backup file; no file was prepared');
    }
    if (headers['X-OpenHMI-Project'] && response.headers.get('X-OpenHMI-Project') !== headers['X-OpenHMI-Project']) {
      const error = new Error('Backup belongs to a different project. Reload before exporting again.'); error.requiresReview = true; throw error;
    }
    const declared = response.headers.get('Content-Length');
    if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > MAX_BACKUP_BYTES)) throw new Error('Backup download size could not be confirmed; no file was prepared');
    const blob = await boundedBody(response, MAX_BACKUP_BYTES);
    if ((declared !== null && Number(declared) !== blob.size) || !await isCompleteBackupZip(blob)) {
      throw new Error('Backup response is incomplete or is not a supported complete backup; no file was prepared');
    }
    return { blob, filename: 'project.openhmi.zip' };
  } catch (error) { await response.body?.cancel().catch(() => {}); if (!Number.isInteger(error.status)) error.message = `Complete backup download failed: ${error.message}`; throw error; }
}

export function saveWorkspaceBackup({ blob, filename }) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = filename;
  document.body.append(link);
  try { link.click(); }
  finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
}
