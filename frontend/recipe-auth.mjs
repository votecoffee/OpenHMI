import { api, json } from './api.mjs';

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const user = value => record(value) && typeof value.name === 'string'
  && Array.isArray(value.roles) && value.roles.every(role => typeof role === 'string');

export function requireRecipeSession(session) {
  if (!record(session) || typeof session.configured !== 'boolean'
    || (session.user !== null && !user(session.user)) || (!session.configured && session.user !== null)) {
    throw new Error('Invalid recipe session response');
  }
  return session;
}

export function requireRecipeSignIn(result) {
  if (!record(result) || !user(result.user)) throw new Error('Invalid recipe sign-in response. Refresh recipes to verify the session.');
  return result;
}

export function requireRecipeSignOut(result) {
  if (result?.ok !== true) throw new Error('Invalid recipe sign-out response. Refresh recipes to verify the session.');
  return result;
}

export const readRecipeSession = async () => requireRecipeSession(await api('/api/recipe-auth/session'));
export const signInRecipe = async (name, password) => requireRecipeSignIn(await api('/api/recipe-auth/login', json('POST', { name, password })));
export const signOutRecipe = async () => requireRecipeSignOut(await api('/api/recipe-auth/logout', json('POST', {})));
