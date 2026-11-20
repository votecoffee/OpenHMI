import { api } from './api.mjs';

export const securitySessionPath = '/api/security/session';
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function requireIdentitySnapshot(identity) {
  const strings = values => Array.isArray(values) && values.every(value => typeof value === 'string');
  const { configured, windows_enabled, windows_available, user, groups } = identity ?? {};
  const validGroup = group => isRecord(group) && typeof group.name === 'string'
    && typeof group.color === 'string' && strings(group.permissions);
  const validUser = user === null || (isRecord(user) && typeof user.name === 'string'
    && ['local', 'windows'].includes(user.provider) && strings(user.groups)
    && strings(user.permissions) && strings(user.roles));
  if (typeof configured !== 'boolean' || typeof windows_enabled !== 'boolean'
    || typeof windows_available !== 'boolean' || !Array.isArray(groups) || !groups.every(validGroup)
    || !validUser || (!configured && user !== null)) {
    throw new Error('Invalid HMI identity status response');
  }
  return identity;
}

export async function readSecuritySession() {
  return requireIdentitySnapshot(await api(securitySessionPath));
}
