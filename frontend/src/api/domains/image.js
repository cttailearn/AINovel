import { apiRequest, uploadWithProgress } from '../base.js';

export const imageApi = {
  listModels: (options) => apiRequest('/image/models', options),
  listEnabledModels: (options) => apiRequest('/image/models/enabled', options),
  generate: (payload, options) =>
    apiRequest('/image/generate', { method: 'POST', body: payload, ...options }),
  uploadReference: (file, { signal } = {}) =>
    uploadWithProgress('/image/reference-upload', file, {
      fieldName: 'file',
      signal,
    }),
};
