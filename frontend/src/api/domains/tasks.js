import { API_PREFIX, apiRequest } from '../base.js';

export const tasksApi = {
  listActive: ({ kind, subjectId, includeRecent } = {}, options) => {
    const params = new URLSearchParams();
    if (kind) params.set('kind', kind);
    if (subjectId != null) params.set('subject_id', String(subjectId));
    if (includeRecent) params.set('include_recent', 'true');
    const qs = params.toString();
    return apiRequest(`/tasks/active${qs ? `?${qs}` : ''}`, options);
  },
  get: (taskId, options) => apiRequest(`/tasks/${taskId}`, options),
  cancel: (taskId, options) =>
    apiRequest(`/tasks/${taskId}/cancel`, { method: 'POST', ...options }),
  subscribeUrl: (taskId) => `${API_PREFIX}/tasks/${taskId}/events`,
  putMirror: (clientId, snapshot, options) =>
    apiRequest(`/tasks/mirror/${encodeURIComponent(clientId)}`, {
      method: 'PUT',
      body: snapshot,
      ...options,
    }),
  getMirror: (clientId, options) =>
    apiRequest(`/tasks/mirror/${encodeURIComponent(clientId)}`, options),
};
