import { API_PREFIX, apiRequest, postStream } from '../base.js';

export const enrichmentApi = {
  listProgress: (novelId, options) =>
    apiRequest(`/enrichment/novels/${novelId}/progress`, options),
  getDetail: (chapterId, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}`, options),
  updateDetail: (chapterId, payload, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}`, {
      method: 'PUT',
      body: payload,
      ...options,
    }),
  runSummary: (chapterId, payload, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}/summary`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  runRecognition: (chapterId, payload, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}/recognition`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  runRewrite: (chapterId, payload, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}/rewrite`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  runFull: (chapterId, payload, { onEvent, signal } = {}) =>
    postStream(`/enrichment/novels/${payload.novelId || chapterId}/batch`, {
      ...payload,
      chapter_ids: [chapterId],
    }, { onEvent, signal }),
  batch: (novelId, payload, { onEvent, signal } = {}) =>
    postStream(`/enrichment/novels/${novelId}/batch`, payload, {
      onEvent,
      signal,
    }),
  retryFailed: (novelId, options) =>
    apiRequest(`/enrichment/novels/${novelId}/retry-failed`, {
      method: 'POST',
      ...options,
    }),
  reset: (novelId, options) =>
    apiRequest(`/enrichment/novels/${novelId}/reset`, {
      method: 'POST',
      ...options,
    }),
  exportUrl: (novelId) =>
    `${API_PREFIX}/enrichment/novels/${novelId}/export`,
  diff: (chapterId, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}/diff`, options),
  apply: (chapterId, payload = {}, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}/apply`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  revert: (chapterId, payload = {}, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}/revert`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  history: (chapterId, options) =>
    apiRequest(`/enrichment/chapters/${chapterId}/history`, options),
};
