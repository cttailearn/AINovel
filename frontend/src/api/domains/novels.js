import { API_PREFIX, apiRequest, postStream, uploadWithProgress } from '../base.js';

export const novelsApi = {
  list: (options) => apiRequest('/novels', options),
  detail: (id, options) => apiRequest(`/novels/${id}`, options),
  update: (id, payload, options) =>
    apiRequest(`/novels/${id}`, { method: 'PUT', body: payload, ...options }),
  remove: (id, options) =>
    apiRequest(`/novels/${id}`, { method: 'DELETE', ...options }),
  chapter: (novelId, chapterId, options) =>
    apiRequest(`/novels/${novelId}/chapters/${chapterId}`, options),
  updateChapter: (novelId, chapterId, payload, options) =>
    apiRequest(`/novels/${novelId}/chapters/${chapterId}`, {
      method: 'PUT',
      body: payload,
      ...options,
    }),
  setParseRule: (id, rule, options) =>
    apiRequest(`/novels/${id}/parse-rule`, {
      method: 'PUT',
      body: { rule },
      ...options,
    }),
  parse: (id, rule, options) =>
    apiRequest(`/novels/${id}/parse`, {
      method: 'POST',
      body: { rule },
      ...options,
    }),
  parsePreview: (id, rule, options) =>
    apiRequest(`/novels/${id}/parse-preview`, {
      method: 'POST',
      body: { rule },
      ...options,
    }),
  parseFixed: (id, chunkSize, options) =>
    apiRequest(`/novels/${id}/parse-fixed`, {
      method: 'POST',
      body: { chunk_size: chunkSize },
      ...options,
    }),
  raw: (id, chunkSize, options) =>
    apiRequest(`/novels/${id}/raw?chunk_size=${chunkSize}`, options),
  upload: (file, { onProgress, signal } = {}) =>
    uploadWithProgress('/novels/upload', file, { onProgress, signal }),
  listCharacters: (id, options) =>
    apiRequest(`/novels/${id}/knowledge-graph`, options),
  extractCharacters: (id, payload, options) =>
    apiRequest(`/novels/${id}/knowledge-graph`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  extractCharactersStream: (id, payload, { onEvent, signal } = {}) =>
    postStream(`/novels/${id}/knowledge-graph/stream`, payload, { onEvent, signal }),
  extractCharactersV2: (id, payload, options) =>
    apiRequest(`/novels/${id}/knowledge-graph/v2`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  extractCharactersStreamV2: (id, payload, { onEvent, signal } = {}) =>
    postStream(`/novels/${id}/knowledge-graph/v2/stream`, payload, { onEvent, signal }),
  reExtractKnowledgeGraph: (id, payload, options) =>
    apiRequest(`/novels/${id}/knowledge-graph/re-extract`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  deleteKnowledgeGraph: (id, options) =>
    apiRequest(`/novels/${id}/knowledge-graph`, {
      method: 'DELETE',
      ...options,
    }),
  getKgStats: (id, options) =>
    apiRequest(`/novels/${id}/kg-stats`, options),
  exportUrl: (novelId) => `${API_PREFIX}/enrichment/novels/${novelId}/export`,
};
