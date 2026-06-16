import { apiRequest } from '../base.js';

export const modelsApi = {
  list: () => apiRequest('/models'),
  enabled: () => apiRequest('/models/enabled'),
  create: (payload, options) =>
    apiRequest('/models', { method: 'POST', body: payload, ...options }),
  update: (id, payload, options) =>
    apiRequest(`/models/${id}`, { method: 'PUT', body: payload, ...options }),
  toggle: (id, enabled, options) =>
    apiRequest(`/models/${id}/toggle?enabled=${enabled ? 1 : 0}`, {
      method: 'PATCH',
      ...options,
    }),
  remove: (id, options) =>
    apiRequest(`/models/${id}`, { method: 'DELETE', ...options }),
  test: (payload, options) =>
    apiRequest('/models/test', { method: 'POST', body: payload, ...options }),
};
