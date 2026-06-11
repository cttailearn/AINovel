// 全局后端连接状态 (UX-#10)
// - AppShell 顶层周期性 ping /api/health
// - 子组件用 useConnection() 读取状态
// - writeGuard() 在后端断开时阻止写操作
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { ApiError, apiRequest } from '../api/client.js';

const ConnectionContext = createContext(null);

const PING_INTERVAL_MS = 8_000;   // 8s 心跳
const PING_TIMEOUT_MS = 3_500;    // 单次 3.5s 超时
const RETRY_BACKOFF_MS = 2_000;   // 断开后 2s 重试

// 写操作判定: HTTP 方法 != GET/HEAD
const WRITE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function ConnectionProvider({ children }) {
  const [status, setStatus] = useState('connecting'); // connecting | ok | error
  const [lastOkAt, setLastOkAt] = useState(null);
  const [lastErrorAt, setLastErrorAt] = useState(null);
  const [retryIn, setRetryIn] = useState(0);
  const manualOverrideRef = useRef(false);

  const check = useCallback(async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), PING_TIMEOUT_MS);
    try {
      await apiRequest('/health', { signal: controller.signal });
      setStatus('ok');
      setLastOkAt(Date.now());
      setRetryIn(0);
    } catch (e) {
      if (manualOverrideRef.current) return; // 用户主动忽略
      setStatus('error');
      setLastErrorAt(Date.now());
      setRetryIn(RETRY_BACKOFF_MS / 1000);
    } finally {
      clearTimeout(timer);
    }
  }, []);

  // 周期 ping
  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const tick = async () => {
      if (cancelled) return;
      await check();
      const delay = status === 'error' ? RETRY_BACKOFF_MS : PING_INTERVAL_MS;
      timer = setTimeout(tick, delay);
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  // 写操作拦截: 包装 apiRequest, 断开时直接抛错
  const guardedRequest = useCallback(async (path, options = {}) => {
    const method = (options.method || 'GET').toUpperCase();
    if (status === 'error' && WRITE_METHODS.has(method)) {
      throw new ApiError('后端连接已断开, 无法执行写操作. 请等待自动重连.', 0, null);
    }
    return apiRequest(path, options);
  }, [status]);

  const ignoreOnce = useCallback(() => {
    manualOverrideRef.current = true;
    setStatus('ok');
  }, []);

  // 倒计时
  useEffect(() => {
    if (status !== 'error' || retryIn <= 0) return undefined;
    const t = setInterval(() => {
      setRetryIn((s) => Math.max(0, s - 1));
    }, 1000);
    return () => clearInterval(t);
  }, [status, retryIn]);

  const value = {
    status,
    lastOkAt,
    lastErrorAt,
    retryIn,
    check,
    ignoreOnce,
    guardedRequest,
  };

  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection() {
  const ctx = useContext(ConnectionContext);
  if (!ctx) {
    // 没包 Provider 时降级 — 返回 ok 状态, 不影响功能
    return {
      status: 'ok',
      lastOkAt: null,
      lastErrorAt: null,
      retryIn: 0,
      check: async () => {},
      ignoreOnce: () => {},
      guardedRequest: apiRequest,
    };
  }
  return ctx;
}
