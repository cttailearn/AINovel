import { apiRequest } from '../base.js';

export const promptsApi = {
  list: (options) => apiRequest('/prompts', options),
  detail: (id, options) => apiRequest(`/prompts/${id}`, options),
  update: (id, payload, options) =>
    apiRequest(`/prompts/${id}`, { method: 'PUT', body: payload, ...options }),
  reset: (id, options) =>
    apiRequest(`/prompts/reset/${id}`, { method: 'POST', ...options }),
  create: (payload, options) =>
    apiRequest('/prompts', { method: 'POST', body: payload, ...options }),
  remove: (id, options) =>
    apiRequest(`/prompts/${id}`, { method: 'DELETE', ...options }),
};
