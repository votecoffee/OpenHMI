import { api, json } from './api.mjs';

export function publicationStatus() {
  return api('/api/security/publication');
}

export function claimPublicationStation(client, renew = false) {
  return api('/api/security/publication/claim' + (renew ? '?renew=true' : ''), json('POST', { client }));
}

export function releasePublicationStation(client) {
  return api('/api/security/publication/release', json('POST', { client }));
}
