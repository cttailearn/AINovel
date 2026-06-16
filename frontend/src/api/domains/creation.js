import { API_PREFIX, apiRequest, postStream } from '../base.js';

export const creationApi = {
  listProjects: (options) => apiRequest('/creation/projects', options),
  createProject: (payload, options) =>
    apiRequest('/creation/projects', { method: 'POST', body: payload, ...options }),
  getProject: (id, options) =>
    apiRequest(`/creation/projects/${id}`, options),
  updateProject: (id, payload, options) =>
    apiRequest(`/creation/projects/${id}`, { method: 'PUT', body: payload, ...options }),
  deleteProject: (id, options) =>
    apiRequest(`/creation/projects/${id}`, { method: 'DELETE', ...options }),
  duplicateProject: (id, options) =>
    apiRequest(`/creation/projects/${id}/duplicate`, { method: 'POST', ...options }),
  getKG: (projectId, options) =>
    apiRequest(`/creation/projects/${projectId}/kg`, options),
  seedKG: (projectId, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/seed`, {
      method: 'POST',
      ...options,
    }),
  clearKG: (projectId, options) =>
    apiRequest(`/creation/projects/${projectId}/kg`, {
      method: 'DELETE',
      ...options,
    }),
  createKGCharacter: (projectId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/characters`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  updateKGCharacter: (projectId, entityId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/characters/${encodeURIComponent(entityId)}`, {
      method: 'PUT',
      body: payload,
      ...options,
    }),
  deleteKGCharacter: (projectId, entityId, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/characters/${encodeURIComponent(entityId)}`, {
      method: 'DELETE',
      ...options,
    }),
  createKGEvent: (projectId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/events`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  updateKGEvent: (projectId, entityId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/events/${encodeURIComponent(entityId)}`, {
      method: 'PUT',
      body: payload,
      ...options,
    }),
  deleteKGEvent: (projectId, entityId, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/events/${encodeURIComponent(entityId)}`, {
      method: 'DELETE',
      ...options,
    }),
  createKGLocation: (projectId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/locations`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  updateKGLocation: (projectId, entityId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/locations/${encodeURIComponent(entityId)}`, {
      method: 'PUT',
      body: payload,
      ...options,
    }),
  deleteKGLocation: (projectId, entityId, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/locations/${encodeURIComponent(entityId)}`, {
      method: 'DELETE',
      ...options,
    }),
  createKGCeRelation: (projectId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/character-event-relations`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  deleteKGRelation: (projectId, relKind, relId, options) =>
    apiRequest(`/creation/projects/${projectId}/kg/relations/${relKind}/${relId}`, {
      method: 'DELETE',
      ...options,
    }),
  listPlotThreads: (projectId, status, options) => {
    const q = status ? `?status=${encodeURIComponent(status)}` : '';
    return apiRequest(`/creation/projects/${projectId}/plot-threads${q}`, options);
  },
  createPlotThread: (projectId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/plot-threads`, {
      method: 'POST',
      body: payload,
      ...options,
    }),
  updatePlotThread: (projectId, threadId, payload, options) =>
    apiRequest(`/creation/projects/${projectId}/plot-threads/${encodeURIComponent(threadId)}`, {
      method: 'PUT',
      body: payload,
      ...options,
    }),
  deletePlotThread: (projectId, threadId, options) =>
    apiRequest(`/creation/projects/${projectId}/plot-threads/${encodeURIComponent(threadId)}`, {
      method: 'DELETE',
      ...options,
    }),
  listChapters: (projectId, options) =>
    apiRequest(`/creation/projects/${projectId}/chapters`, options),
  reorderChapters: (projectId, orders, options) =>
    apiRequest(`/creation/projects/${projectId}/chapters/reorder`, {
      method: 'POST',
      body: { orders },
      ...options,
    }),
  getChapter: (chapterId, options) =>
    apiRequest(`/creation/chapters/${chapterId}`, options),
  selectVariant: (chapterId, variantId, options) =>
    apiRequest(`/creation/chapters/${chapterId}/select`, {
      method: 'POST',
      body: { variant_id: variantId },
      ...options,
    }),
  updateContent: (chapterId, content, options) =>
    apiRequest(`/creation/chapters/${chapterId}/content`, {
      method: 'PUT',
      body: { content },
      ...options,
    }),
  confirmChapter: (chapterId, options) =>
    apiRequest(`/creation/chapters/${chapterId}/confirm`, {
      method: 'POST',
      ...options,
    }),
  deleteChapter: (chapterId, options) =>
    apiRequest(`/creation/chapters/${chapterId}`, {
      method: 'DELETE',
      ...options,
    }),
  getVariantsHistory: (chapterId, options) =>
    apiRequest(`/creation/chapters/${chapterId}/variants/history`, options),
  exportChapterUrl: (chapterId, format = 'txt') =>
    `${API_PREFIX}/creation/chapters/${chapterId}/export?format=${encodeURIComponent(format)}`,
  exportProjectUrl: (projectId, format = 'txt') =>
    `${API_PREFIX}/creation/projects/${projectId}/export?format=${encodeURIComponent(format)}`,
  generate: (projectId, payload, { onEvent, signal } = {}) =>
    postStream(`/creation/projects/${projectId}/chapters/generate`, payload, {
      onEvent,
      signal,
    }),
  intakeNext: (payload, options) =>
    apiRequest('/creation/intake/next', {
      method: 'POST',
      body: payload,
      ...options,
    }),
  intakeSynthesize: (payload, options) =>
    apiRequest('/creation/intake/synthesize', {
      method: 'POST',
      body: payload,
      ...options,
    }),
};
