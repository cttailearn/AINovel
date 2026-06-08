import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { ApiError, api } from '../api/client.js';

const STEPS = ['summary', 'recognition', 'rewrite'];

const EnrichmentTaskContext = createContext(null);

/**
 * 全局加料任务状态.
 *
 * 设计要点: 把 batch SSE 流的生命周期从 EnrichmentWorkbench 提到
 * App 顶层, 这样即使用户切换到「图像生成」或「系统设置」, 任务的
 * AbortController 仍然存活, 后端继续跑. 任务结束时再从 workbench
 * 拉一次最新 progress 即可保持 UI 一致.
 */
export function EnrichmentTaskProvider({ children }) {
  const [running, setRunning] = useState(false);
  const [novelId, setNovelId] = useState(null);
  const [novelTitle, setNovelTitle] = useState('');
  const [stepProgress, setStepProgress] = useState(null);
  // 总步数 done / total, 用于顶部进度条
  const [aggregate, setAggregate] = useState({ done: 0, total: 0 });
  const [currentChapter, setCurrentChapter] = useState(null);
  const [lastEvent, setLastEvent] = useState(null); // 'start' | 'complete' | 'error' | 'cancelled' | null
  const [errorMessage, setErrorMessage] = useState('');
  const [startTime, setStartTime] = useState(null);
  const [version, setVersion] = useState(0); // 任务完成/失败后用来触发 workbench 刷新

  const controllerRef = useRef(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const recomputeAggregate = useCallback((sp) => {
    if (!sp) return { done: 0, total: 0 };
    let done = 0;
    let total = 0;
    STEPS.forEach((s) => {
      const v = sp[s];
      if (!v) return;
      done += Number(v.done || 0);
      total += Number(v.total || 0);
    });
    return { done, total };
  }, []);

  const startBatch = useCallback(
    ({
      targetNovelId,
      novelTitle: title,
      modelConfigId,
      steps,
      chapterIds = null,
      concurrency = 2,
      skipExisting = true,
    }) => {
      if (!targetNovelId || !modelConfigId) return;
      if (controllerRef.current) {
        try { controllerRef.current.abort(); } catch { /* noop */ }
        controllerRef.current = null;
      }
      const controller = new AbortController();
      controllerRef.current = controller;
      setRunning(true);
      setNovelId(targetNovelId);
      setNovelTitle(title || '');
      setLastEvent('start');
      setErrorMessage('');
      setStartTime(Date.now());
      setStepProgress({ summary: { done: 0, total: 0 } });
      setCurrentChapter(null);
      setAggregate({ done: 0, total: 0 });
      setVersion((v) => v + 1);

      const onEvent = (payload) => {
        if (!payload || !isMountedRef.current) return;
        if (payload.event === 'start') {
          setStepProgress(payload.step_progress || null);
          setAggregate(recomputeAggregate(payload.step_progress || null));
        } else if (payload.event === 'chapter_start') {
          setCurrentChapter({
            chapter_id: payload.chapter_id,
            chapter_number: payload.chapter_number,
            title: payload.title,
            step: payload.step,
          });
        } else if (payload.event === 'chapter_done' || payload.event === 'skip') {
          setStepProgress((prev) => {
            const next = { ...(prev || {}) };
            Object.keys(payload.step_progress || {}).forEach((k) => {
              if (!STEPS.includes(k)) return;
              next[k] = { ...(next[k] || {}), ...(payload.step_progress[k] || {}) };
            });
            setAggregate(recomputeAggregate(next));
            return next;
          });
          if (payload.event === 'chapter_done') {
            setCurrentChapter({
              chapter_id: payload.chapter_id,
              chapter_number: payload.chapter_number,
              title: payload.title,
              step: payload.step,
              success: payload.success,
            });
          }
        } else if (payload.event === 'step_done') {
          setStepProgress((prev) => {
            const next = { ...(prev || {}) };
            if (payload.step) {
              next[payload.step] = { done: payload.done, total: payload.total };
            }
            setAggregate(recomputeAggregate(next));
            return next;
          });
        } else if (payload.event === 'complete') {
          setLastEvent('complete');
          setRunning(false);
          setControllerNull();
          setVersion((v) => v + 1);
        } else if (payload.event === 'cancelled') {
          setLastEvent('cancelled');
          setRunning(false);
          setControllerNull();
          setVersion((v) => v + 1);
        } else if (payload.event === 'error') {
          setLastEvent('error');
          setErrorMessage(payload.message || '未知错误');
          setRunning(false);
          setControllerNull();
          setVersion((v) => v + 1);
        }
      };

      const setControllerNull = () => {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
      };

      api.enrichment
        .batch(
          targetNovelId,
          {
            model_config_id: modelConfigId,
            steps,
            chapter_ids: chapterIds,
            concurrency,
            skip_existing: skipExisting,
          },
          { signal: controller.signal, onEvent }
        )
        .catch((err) => {
          if (!isMountedRef.current) return;
          if (err && (err.name === 'AbortError' || err.message === '请求已取消')) {
            setLastEvent('cancelled');
          } else {
            setLastEvent('error');
            setErrorMessage(
              err instanceof ApiError ? err.message : err?.message || '请求失败'
            );
          }
          setRunning(false);
          setControllerNull();
          setVersion((v) => v + 1);
        });
    },
    [recomputeAggregate]
  );

  const cancel = useCallback(() => {
    if (controllerRef.current) {
      try { controllerRef.current.abort(); } catch { /* noop */ }
      controllerRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    setRunning(false);
    setNovelId(null);
    setNovelTitle('');
    setStepProgress(null);
    setAggregate({ done: 0, total: 0 });
    setCurrentChapter(null);
    setLastEvent(null);
    setErrorMessage('');
    setStartTime(null);
  }, []);

  const value = useMemo(
    () => ({
      running,
      novelId,
      novelTitle,
      stepProgress,
      aggregate,
      currentChapter,
      lastEvent,
      errorMessage,
      startTime,
      version,
      startBatch,
      cancel,
      reset,
    }),
    [
      running,
      novelId,
      novelTitle,
      stepProgress,
      aggregate,
      currentChapter,
      lastEvent,
      errorMessage,
      startTime,
      version,
      startBatch,
      cancel,
      reset,
    ]
  );

  return (
    <EnrichmentTaskContext.Provider value={value}>
      {children}
    </EnrichmentTaskContext.Provider>
  );
}

export function useEnrichmentTask() {
  const ctx = useContext(EnrichmentTaskContext);
  if (!ctx) {
    throw new Error('useEnrichmentTask must be used inside EnrichmentTaskProvider');
  }
  return ctx;
}
