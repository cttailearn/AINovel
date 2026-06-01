import { useCallback, useEffect, useRef, useState } from 'react';

export function useApi(requestFn, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const abortRef = useRef(null);
  const mountedRef = useRef(true);

  const run = useCallback(
    async (...args) => {
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      try {
        const result = await requestFn(...args, { signal: controller.signal });
        if (mountedRef.current && abortRef.current === controller) {
          setData(result);
          setError(null);
        }
        return result;
      } catch (err) {
        if (err && err.name === 'AbortError') return null;
        if (mountedRef.current) {
          setError(err);
          setData(null);
        }
        throw err;
      } finally {
        if (mountedRef.current && abortRef.current === controller) {
          setLoading(false);
        }
      }
    },
    deps
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  const refetch = useCallback(() => run(), [run]);

  return { data, error, loading, refetch, run };
}
