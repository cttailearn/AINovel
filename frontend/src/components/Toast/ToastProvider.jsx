import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

const ToastContext = createContext(null);

let counter = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timersRef = useRef(new Map());

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const handle = timersRef.current.get(id);
    if (handle) {
      clearTimeout(handle);
      timersRef.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (message, { type = 'info', duration = 3500 } = {}) => {
      counter += 1;
      const id = `t-${Date.now()}-${counter}`;
      setToasts((prev) => [...prev, { id, message, type }]);
      const handle = setTimeout(() => dismiss(id), duration);
      timersRef.current.set(id, handle);
      return id;
    },
    [dismiss]
  );

  useEffect(() => {
    return () => {
      timersRef.current.forEach((h) => clearTimeout(h));
      timersRef.current.clear();
    };
  }, []);

  const api = useMemo(
    () => ({
      show: push,
      success: (m, opts) => push(m, { ...(opts || {}), type: 'success' }),
      error: (m, opts) => push(m, { ...(opts || {}), type: 'error' }),
      info: (m, opts) => push(m, { ...(opts || {}), type: 'info' }),
      dismiss,
    }),
    [push, dismiss]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            <span className="toast-message">{t.message}</span>
            <button
              className="toast-close"
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="关闭通知"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return ctx;
}
