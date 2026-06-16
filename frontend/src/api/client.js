import { apiRequest, ApiError, API_PREFIX, getEventStream, postStream, uploadWithProgress } from './base.js';
import { modelsApi } from './domains/models.js';
import { novelsApi } from './domains/novels.js';
import { promptsApi } from './domains/prompts.js';
import { imageApi } from './domains/image.js';
import { enrichmentApi } from './domains/enrichment.js';
import { tasksApi } from './domains/tasks.js';
import { creationApi } from './domains/creation.js';

export { API_PREFIX, ApiError, apiRequest, getEventStream, postStream, uploadWithProgress };

export const api = {
  health: () => apiRequest('/health'),
  models: modelsApi,
  novels: novelsApi,
  prompts: promptsApi,
  image: imageApi,
  enrichment: enrichmentApi,
  tasks: tasksApi,
  creation: creationApi,
};
