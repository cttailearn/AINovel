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
      apiRequest(`/novels/${id}/characters`, options),
    extractCharacters: (id, payload, options) =>
      apiRequest(`/novels/${id}/characters`, {
        method: 'POST',
        body: payload,
        ...options,
      }),
  },
};
