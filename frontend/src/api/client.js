const API_PREFIX = (typeof window !== 'undefined' && window.__TAURI_INTERNALS__)
  ? 'http://127.0.0.1:8008/api'
  : '/api';

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

function joinUrl(base, path) {
  if (!path) return base;
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  if (!path.startsWith('/')) path = `/${path}`;
  return `${base}${path}`;
}

function buildHeaders(extra, isForm) {
  const headers = { Accept: 'application/json', ...(extra || {}) };
  if (!isForm && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  return headers;
}

async function parseResponse(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function raiseIfError(response, payload) {
  if (response.ok) return payload;
  const detail = payload && payload.detail ? payload.detail : response.statusText;
  throw new ApiError(detail || `请求失败 (${response.status})`, response.status, payload);
}

export async function apiRequest(
  path,
  { method = 'GET', body, headers, signal } = {}
) {
  const isForm = body instanceof FormData;
  const response = await fetch(joinUrl(API_PREFIX, path), {
    method,
    headers: buildHeaders(headers, isForm),
    body: isForm ? body : body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const payload = await parseResponse(response);
  return raiseIfError(response, payload);
}

export function uploadWithProgress(
  path,
  file,
  { onProgress, fieldName = 'file', extra, signal } = {}
) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append(fieldName, file);
    if (extra) {
      for (const [k, v] of Object.entries(extra)) {
        formData.append(k, v);
      }
    }
    const xhr = new XMLHttpRequest();
    xhr.open('POST', joinUrl(API_PREFIX, path));
    if (signal) {
      if (signal.aborted) {
        reject(new DOMException('请求已取消', 'AbortError'));
        return;
      }
      signal.addEventListener('abort', () => xhr.abort());
    }
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && typeof onProgress === 'function') {
        onProgress({
          loaded: event.loaded,
          total: event.total,
          ratio: event.loaded / event.total,
        });
      }
    };
    xhr.onload = () => {
      const text = xhr.responseText || '';
      let payload = null;
      if (text) {
        try {
          payload = JSON.parse(text);
        } catch {
          payload = text;
        }
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload);
      } else {
        const detail = payload && payload.detail ? payload.detail : xhr.statusText;
        reject(
          new ApiError(
            detail || `上传失败 (${xhr.status})`,
            xhr.status,
            payload
          )
        );
      }
    };
    xhr.onerror = () =>
      reject(new ApiError('网络错误', 0, null));
    xhr.onabort = () =>
      reject(new DOMException('请求已取消', 'AbortError'));
    xhr.send(formData);
  });
}

async function readSseStream(response, onEvent) {
  const reader = response.body && response.body.getReader
    ? response.body.getReader()
    : null;
  if (!reader) {
    // Fallback: read entire text and split by lines.
    const text = await response.text();
    for (const raw of text.split(/\r?\n/)) {
      if (!raw.startsWith('data:')) continue;
      const body = raw.slice(5).trim();
      if (!body) continue;
      try {
        const obj = JSON.parse(body);
        onEvent?.(obj);
      } catch {
        // ignore
      }
    }
    return;
  }
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const raw of block.split(/\r?\n/)) {
        if (!raw.startsWith('data:')) continue;
        const body = raw.slice(5).trim();
        if (!body) continue;
        try {
          const obj = JSON.parse(body);
          onEvent?.(obj);
        } catch {
          // ignore non-JSON keepalive lines
        }
      }
    }
  }
  if (buffer.trim()) {
    const tail = buffer.trim();
    if (tail.startsWith('data:')) {
      const body = tail.slice(5).trim();
      if (body) {
        try {
          onEvent?.(JSON.parse(body));
        } catch {
          // ignore
        }
      }
    }
  }
}

export function postStream(path, body, { onEvent, signal } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', joinUrl(API_PREFIX, path));
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('Accept', 'text/event-stream');
    if (signal) {
      if (signal.aborted) {
        reject(new DOMException('请求已取消', 'AbortError'));
        return;
      }
      signal.addEventListener('abort', () => {
        try { xhr.abort(); } catch { /* noop */ }
        reject(new DOMException('请求已取消', 'AbortError'));
      });
    }
    xhr.onerror = () => reject(new ApiError('网络错误', 0, null));
    xhr.onabort = () => reject(new DOMException('请求已取消', 'AbortError'));
    let buffer = '';
    xhr.onreadystatechange = () => {
      if (xhr.readyState === 3 || xhr.readyState === 4) {
        const chunk = xhr.responseText.slice(buffer.length);
        buffer = xhr.responseText;
        if (chunk) {
          let idx;
          let work = chunk;
          while ((idx = work.indexOf('\n\n')) >= 0) {
            const block = work.slice(0, idx);
            work = work.slice(idx + 2);
            for (const raw of block.split(/\r?\n/)) {
              if (!raw.startsWith('data:')) continue;
              const body = raw.slice(5).trim();
              if (!body) continue;
              try {
                onEvent?.(JSON.parse(body));
              } catch {
                // ignore
              }
            }
          }
        }
      }
      if (xhr.readyState === 4) {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          let payload = null;
          if (xhr.responseText) {
            try { payload = JSON.parse(xhr.responseText); } catch { /* noop */ }
          }
          const detail = payload && payload.detail ? payload.detail : xhr.statusText;
          reject(new ApiError(detail || `请求失败 (${xhr.status})`, xhr.status, payload));
        }
      }
    };
    xhr.send(JSON.stringify(body));
  });
}


export const api = {
  health: () => apiRequest('/health'),
  models: {
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
  },
  novels: {
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
      postStream(`/novels/${id}/knowledge-graph/stream`, payload, {
        onEvent,
        signal,
      }),
    extractCharactersV2: (id, payload, options) =>
      apiRequest(`/novels/${id}/knowledge-graph/v2`, {
        method: 'POST',
        body: payload,
        ...options,
      }),
    extractCharactersStreamV2: (id, payload, { onEvent, signal } = {}) =>
      postStream(`/novels/${id}/knowledge-graph/v2/stream`, payload, {
        onEvent,
        signal,
      }),
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
  },
  prompts: {
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
  },
  image: {
    listModels: (options) => apiRequest('/image/models', options),
    listEnabledModels: (options) => apiRequest('/image/models/enabled', options),
    generate: (payload, options) =>
      apiRequest('/image/generate', { method: 'POST', body: payload, ...options }),
    uploadReference: (file, { signal } = {}) =>
      uploadWithProgress('/image/reference-upload', file, {
        fieldName: 'file',
        signal,
      }),
  },
  enrichment: {
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
    // v0.2.1: 一键生成 (summary + recognition + rewrite) 走 batch
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
    // v0.2: 应用 / 回滚 / 历史 / diff
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
  },
  creation: {
    // 项目
    listProjects: (options) => apiRequest('/creation/projects', options),
    createProject: (payload, options) =>
      apiRequest('/creation/projects', { method: 'POST', body: payload, ...options }),
    getProject: (id, options) =>
      apiRequest(`/creation/projects/${id}`, options),
    updateProject: (id, payload, options) =>
      apiRequest(`/creation/projects/${id}`, { method: 'PUT', body: payload, ...options }),
    deleteProject: (id, options) =>
      apiRequest(`/creation/projects/${id}`, { method: 'DELETE', ...options }),
    // 知识图谱
    getKG: (projectId, options) =>
      apiRequest(`/creation/projects/${projectId}/kg`, options),
    seedKG: (projectId, options) =>
      apiRequest(`/creation/projects/${projectId}/kg/seed`, {
        method: 'POST', ...options,
      }),
    clearKG: (projectId, options) =>
      apiRequest(`/creation/projects/${projectId}/kg`, {
        method: 'DELETE', ...options,
      }),
    // 章节
    listChapters: (projectId, options) =>
      apiRequest(`/creation/projects/${projectId}/chapters`, options),
    getChapter: (chapterId, options) =>
      apiRequest(`/creation/chapters/${chapterId}`, options),
    selectVariant: (chapterId, variantId, options) =>
      apiRequest(`/creation/chapters/${chapterId}/select`, {
        method: 'POST', body: { variant_id: variantId }, ...options,
      }),
    updateContent: (chapterId, content, options) =>
      apiRequest(`/creation/chapters/${chapterId}/content`, {
        method: 'PUT', body: { content }, ...options,
      }),
    confirmChapter: (chapterId, options) =>
      apiRequest(`/creation/chapters/${chapterId}/confirm`, {
        method: 'POST', ...options,
      }),
    deleteChapter: (chapterId, options) =>
      apiRequest(`/creation/chapters/${chapterId}`, {
        method: 'DELETE', ...options,
      }),
    // 导出章节: 返回 { url, filename } 用于触发浏览器下载
    exportChapterUrl: (chapterId, format = 'txt') =>
      `${API_PREFIX}/creation/chapters/${chapterId}/export?format=${encodeURIComponent(format)}`,
    // 生成 (SSE)
    generate: (projectId, payload, { onEvent, signal } = {}) =>
      postStream(`/creation/projects/${projectId}/chapters/generate`, payload, {
        onEvent,
        signal,
      }),
    // 新建项目引导式问答 (Intake wizard)
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
  },
};
