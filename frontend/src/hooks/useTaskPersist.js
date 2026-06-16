import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

function safeReadLocal(storageKey) {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(storageKey);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function safeWriteLocal(storageKey, snapshot) {
  if (typeof window === 'undefined') return;
  try {
    if (snapshot == null) window.localStorage.removeItem(storageKey);
    else window.localStorage.setItem(storageKey, JSON.stringify(snapshot));
  } catch {
    // noop
  }
}

export function useTaskPersist({
  storageKey,
  snapshot,
  onExternalSnapshot,
  mirror = null,
}) {
  const [mirrorWarning, setMirrorWarning] = useState('');
  const channelRef = useRef(null);
  const retryTimerRef = useRef(null);
  const snapshotText = useMemo(
    () => (snapshot == null ? '' : JSON.stringify(snapshot)),
    [snapshot],
  );

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  useEffect(() => () => clearRetry(), [clearRetry]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    if (typeof window.BroadcastChannel === 'undefined') return undefined;
    const channel = new BroadcastChannel(`${storageKey}:broadcast`);
    channelRef.current = channel;
    channel.onmessage = (event) => {
      const next = event?.data?.snapshot ?? null;
      onExternalSnapshot?.(next, 'broadcast');
    };
    return () => {
      channel.close();
      if (channelRef.current === channel) channelRef.current = null;
    };
  }, [onExternalSnapshot, storageKey]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const handleStorage = (event) => {
      if (event.key !== storageKey) return;
      onExternalSnapshot?.(safeReadLocal(storageKey), 'storage');
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, [onExternalSnapshot, storageKey]);

  useEffect(() => {
    const next = snapshot == null ? null : JSON.parse(snapshotText);
    safeWriteLocal(storageKey, next);
    channelRef.current?.postMessage({ snapshot: next, at: Date.now() });
  }, [snapshot, snapshotText, storageKey]);

  useEffect(() => {
    clearRetry();
    if (!mirror || !mirror.clientId || snapshot == null) {
      setMirrorWarning('');
      return undefined;
    }
    let cancelled = false;
    let attempt = 0;
    const delays = [0, 1500, 5000];
    const push = () => {
      const delay = delays[Math.min(attempt, delays.length - 1)];
      retryTimerRef.current = window.setTimeout(async () => {
        if (cancelled) return;
        try {
          await mirror.put(mirror.clientId, JSON.parse(snapshotText));
          if (!cancelled) setMirrorWarning('');
        } catch {
          if (!cancelled) {
            setMirrorWarning('任务未同步到云端，刷新后可能丢失，系统会自动重试。');
            attempt += 1;
            if (attempt < delays.length) push();
          }
        }
      }, delay);
    };
    push();
    return () => {
      cancelled = true;
      clearRetry();
    };
  }, [clearRetry, mirror, snapshot, snapshotText]);

  const restoreMirror = useCallback(async () => {
    if (!mirror || !mirror.clientId || !mirror.get) return null;
    try {
      const res = await mirror.get(mirror.clientId);
      return res?.snapshot ?? null;
    } catch {
      return null;
    }
  }, [mirror]);

  return {
    mirrorWarning,
    restoreMirror,
    readLocal: () => safeReadLocal(storageKey),
  };
}
