import { api, json } from './api.mjs';

export const readRecipeSession = () => api('/api/recipe-auth/session');
export const signInRecipe = (name, password) => api('/api/recipe-auth/login', json('POST', { name, password }));
export const signOutRecipe = () => api('/api/recipe-auth/logout', json('POST', {}));
