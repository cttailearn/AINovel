export const API_PREFIX = (typeof window !== 'undefined' && window.__TAURI_INTERNALS__)
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

export function joinUrl(base, path) {
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
  { method = 'GET', body, headers, signal } = {},
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
  { onProgress, fieldName = 'file', extra, signal } = {},
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
        reject(new ApiError(
          detail || `上传失败 (${xhr.status})`,
          xhr.status,
          payload,
        ));
      }
    };
    xhr.onerror = () => reject(new ApiError('网络错误', 0, null));
    xhr.onabort = () => reject(new DOMException('请求已取消', 'AbortError'));
    xhr.send(formData);
  });
}

async function readSseStream(response, onEvent) {
  const reader = response.body && response.body.getReader
    ? response.body.getReader()
    : null;
  if (!reader) {
    const text = await response.text();
    for (const raw of text.split(/\r?\n/)) {
      if (!raw.startsWith('data:')) continue;
      const body = raw.slice(5).trim();
      if (!body) continue;
      try {
        onEvent?.(JSON.parse(body));
      } catch {
        // noop
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
          onEvent?.(JSON.parse(body));
        } catch {
          // noop
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
          // noop
        }
      }
    }
  }
}

export function postStream(path, body, { onEvent, signal } = {}) {
  return new Promise((resolve, reject) => {
    const controller = new AbortController();
    let closed = false;
    if (signal) {
      if (signal.aborted) {
        reject(new DOMException('请求已取消', 'AbortError'));
        return;
      }
      signal.addEventListener('abort', () => {
        if (closed) return;
        closed = true;
        try { controller.abort(); } catch { /* noop */ }
        reject(new DOMException('请求已取消', 'AbortError'));
      });
    }
    fetch(joinUrl(API_PREFIX, path), {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body ?? {}),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          let payload = null;
          try {
            const text = await response.text();
            payload = text ? JSON.parse(text) : null;
          } catch {
            // noop
          }
          const detail = payload && payload.detail ? payload.detail : response.statusText;
          closed = true;
          reject(new ApiError(
            detail || `请求失败 (${response.status})`,
            response.status,
            payload,
          ));
          return;
        }
        await readSseStream(response, onEvent);
        closed = true;
        resolve();
      })
      .catch((err) => {
        if (closed) return;
        closed = true;
        if (err && (err.name === 'AbortError' || err.message === '请求已取消')) {
          reject(new DOMException('请求已取消', 'AbortError'));
        } else {
          reject(err instanceof Error ? err : new ApiError(String(err), 0, null));
        }
      });
  });
}

export function getEventStream(url, { onEvent, signal } = {}) {
  return new Promise((resolve, reject) => {
    const controller = new AbortController();
    if (signal) {
      if (signal.aborted) {
        reject(new DOMException('请求已取消', 'AbortError'));
        return;
      }
      signal.addEventListener('abort', () => {
        try { controller.abort(); } catch { /* noop */ }
      });
    }
    let closed = false;
    const onAbort = () => {
      if (closed) return;
      closed = true;
      try { controller.abort(); } catch { /* noop */ }
    };
    if (signal) signal.addEventListener('abort', onAbort);
    fetch(url, {
      method: 'GET',
      headers: { Accept: 'text/event-stream' },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          let payload = null;
          try {
            const text = await response.text();
            payload = text ? JSON.parse(text) : null;
          } catch {
            // noop
          }
          const detail = payload && payload.detail ? payload.detail : response.statusText;
          closed = true;
          reject(new ApiError(
            detail || `请求失败 (${response.status})`,
            response.status,
            payload,
          ));
          return;
        }
        const reader = response.body && response.body.getReader
          ? response.body.getReader()
          : null;
        if (!reader) {
          closed = true;
          reject(new ApiError('当前浏览器不支持流式响应', 0, null));
          return;
        }
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        try {
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
                  onEvent?.(JSON.parse(body));
                } catch {
                  // noop
                }
              }
            }
          }
        } catch (err) {
          if (err && err.name === 'AbortError') {
            closed = true;
            reject(new DOMException('请求已取消', 'AbortError'));
            return;
          }
          closed = true;
          reject(err);
          return;
        }
        closed = true;
        if (buffer.trim()) {
          const tail = buffer.trim();
          if (tail.startsWith('data:')) {
            const body = tail.slice(5).trim();
            if (body) {
              try {
                onEvent?.(JSON.parse(body));
              } catch {
                // noop
              }
            }
          }
        }
        resolve();
      })
      .catch((err) => {
        if (closed) return;
        closed = true;
        if (err && (err.name === 'AbortError' || err.message === '请求已取消')) {
          reject(new DOMException('请求已取消', 'AbortError'));
        } else {
          reject(err instanceof Error ? err : new ApiError(String(err), 0, null));
        }
      });
  });
}
