import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { ApiError, api, getEventStream } from '../api/client.js';

const STEPS = ['summary', 'recognition', 'rewrite'];

const EnrichmentTaskContext = createContext(null);

// localStorage key — 持久化最近一次任务状态, 用于刷新页面后恢复 banner.
const STORAGE_KEY = 'ainovel.enrichment.task.v1';

// 状态对象的精简版, 只保留 UI 重建 + 重连所需字段.
const PERSIST_FIELDS = [
  'taskId',
  'running',
  'novelId',
  'novelTitle',
  'stepProgress',
  'aggregate',
  'currentChapter',
  'lastEvent',
  'errorMessage',
  'startTime',
];

function readPersisted() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object') return null;
    return data;
  } catch {
    return null;
  }
}

function writePersisted(snapshot) {
  if (typeof window === 'undefined') return;
  try {
    if (snapshot == null) {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
    }
  } catch {
    /* localStorage 可能被禁用, 静默失败 */
  }
}

/**
 * 全局加料任务状态.
 *
 * 持久化策略
 * ----------
 * 1. ``taskId`` 是后端 TaskRegistry 颁发的全局唯一 ID, 持久化到 localStorage.
 *    页面刷新后, 启动时调用 ``GET /api/tasks/active`` 询问后端: 这个 task
 *    是否还在跑? 如果是, 重新挂上 ``GET /api/tasks/{id}/events`` 即可续上
 *    进度, 不需要用户重新触发加料.
 * 2. 业务进度 (stepProgress / aggregate / currentChapter) 同步写到 localStorage,
 *    在重连的 *第一帧* 就显示出来, 避免 banner 在拿到新事件前变成空.
 * 3. 任务结束 (complete / cancelled / error) 后, banner 仍短暂展示, 用户
 *    可点击关闭, 关闭时再清掉持久化.
 */
export function EnrichmentTaskProvider({ children }) {
  // 从 localStorage 恢复初始值, 让刷新后 banner 立刻有内容.
  const initial = useMemo(() => readPersisted() || {}, []);

  const [taskId, setTaskId] = useState(initial.taskId || null);
  const [running, setRunning] = useState(Boolean(initial.running));
  const [novelId, setNovelId] = useState(initial.novelId || null);
  const [novelTitle, setNovelTitle] = useState(initial.novelTitle || '');
  const [stepProgress, setStepProgress] = useState(initial.stepProgress || null);
  const [aggregate, setAggregate] = useState(
    initial.aggregate || { done: 0, total: 0 }
  );
  const [currentChapter, setCurrentChapter] = useState(initial.currentChapter || null);
  const [lastEvent, setLastEvent] = useState(initial.lastEvent || null);
  const [errorMessage, setErrorMessage] = useState(initial.errorMessage || '');
  const [startTime, setStartTime] = useState(initial.startTime || null);
  const [version, setVersion] = useState(0);

  const controllerRef = useRef(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // 持久化: 任意关键状态变更都写一次 localStorage.
  useEffect(() => {
    if (!running && !lastEvent) {
      // 全部空, 清理
      writePersisted(null);
      return;
    }
    const snap = {
      taskId,
      running,
      novelId,
      novelTitle,
      stepProgress,
      aggregate,
      currentChapter,
      lastEvent,
      errorMessage,
      startTime,
    };
    writePersisted(snap);
  }, [
    taskId,
    running,
    novelId,
    novelTitle,
    stepProgress,
    aggregate,
    currentChapter,
    lastEvent,
    errorMessage,
    startTime,
  ]);

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

  // 业务事件处理: 与 startBatch 复用同一段逻辑
  const handleEvent = useCallback(
    (payload, record) => {
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
        if (controllerRef.current && controllerRef.current.__record === record) {
          controllerRef.current = null;
        }
        setVersion((v) => v + 1);
      } else if (payload.event === 'cancelled') {
        setLastEvent('cancelled');
        setRunning(false);
        if (controllerRef.current && controllerRef.current.__record === record) {
          controllerRef.current = null;
        }
        setVersion((v) => v + 1);
      } else if (payload.event === 'error') {
        setLastEvent('error');
        setErrorMessage(payload.message || '未知错误');
        setRunning(false);
        if (controllerRef.current && controllerRef.current.__record === record) {
          controllerRef.current = null;
        }
        setVersion((v) => v + 1);
      }
    },
    [recomputeAggregate]
  );

  /**
   * 启动新任务. ``onRegistered`` 在拿到后端 task_id 时触发, 让调用方
   * 能立刻知道 taskId, 便于立刻持久化.
   */
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
        // 首个 registered 事件里携带 task_id, 持久化下来
        if (payload && payload.event === 'registered' && payload.task_id) {
          setTaskId(payload.task_id);
          controller.__record = payload.task_id;
          return;
        }
        handleEvent(payload, controller.__record);
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
          if (controllerRef.current === controller) {
            controllerRef.current = null;
          }
          setVersion((v) => v + 1);
        });
    },
    [handleEvent]
  );

  const cancel = useCallback(() => {
    if (controllerRef.current) {
      try { controllerRef.current.abort(); } catch { /* noop */ }
      controllerRef.current = null;
    }
    // 同时通知后端取消, 这样即使前端 AbortController 没起作用, 业务层
    // 也能通过 should_cancel() 优雅退出 (这正是"刷新后仍能取消"的关键).
    if (taskId) {
      api.tasks.cancel(taskId).catch(() => { /* 后端可能已经结束, 忽略 */ });
    }
  }, [taskId]);

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
    setTaskId(null);
    writePersisted(null);
  }, []);

  /**
   * 在 mount 时调用: 检查后端是否还有这个 (kind, subject_id) 的活跃任务,
   * 如果有, 重新挂上 SSE 订阅. 这是"刷新页面后任务不丢"的关键.
   *
   * 失败 / 404 都不抛错, 静默清理.
   */
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let activeController = null;
    (async () => {
      try {
        const rec = await api.tasks.get(taskId);
        if (cancelled) return;
        if (rec && !rec.done) {
          // 任务还在跑, 重新挂 SSE 订阅
          setRunning(true);
          setNovelId(rec.subject_id);
          setNovelTitle(rec.title || '');
          setLastEvent('start');
          if (rec.meta && rec.meta.steps) {
            // 业务事件会重新设置 stepProgress, 这里给个空壳避免 0/0 闪烁
            const empty = {};
            (rec.meta.steps || []).forEach((s) => {
              empty[s] = { done: 0, total: 0 };
            });
            setStepProgress(empty);
          }
          // 用一个新的 AbortController, 通过 controllerRef 持有
          if (controllerRef.current) {
            try { controllerRef.current.abort(); } catch { /* noop */ }
          }
          const controller = new AbortController();
          controller.__record = rec.task_id;
          controllerRef.current = controller;
          activeController = controller;

          getEventStream(api.tasks.subscribeUrl(rec.task_id), {
            signal: controller.signal,
            onEvent: (ev) => {
              if (ev && ev.event === 'subscribed') return; // 内部握手事件
              handleEvent(ev, rec.task_id);
            },
          }).catch((err) => {
            if (!isMountedRef.current) return;
            if (err && (err.name === 'AbortError' || err.message === '请求已取消')) {
              return; // 用户主动取消
            }
            // 订阅本身出错: 不当成 task 失败, 让用户手动处理
            // eslint-disable-next-line no-console
            console.warn('Re-subscribe to enrichment task failed', err);
          });
        } else if (rec && rec.done) {
          // 任务已结束, 同步到 UI 终态
          if (rec.final_state) {
            setLastEvent(rec.final_state);
            setRunning(false);
          } else {
            // 没有 final_state 视为完成
            setLastEvent('complete');
            setRunning(false);
          }
        } else {
          // 拿不到, 清掉持久化
          writePersisted(null);
          setTaskId(null);
        }
      } catch (err) {
        if (cancelled) return;
        if (err && err.status === 404) {
          // 后端已 GC, 清理
          writePersisted(null);
          setTaskId(null);
        }
        // 其它错误 (后端不可用等) 静默, 不影响 UI
      }
    })();
    return () => {
      cancelled = true;
      if (activeController) {
        try { activeController.abort(); } catch { /* noop */ }
      }
    };
  // 仅在 mount + taskId 变化时检查
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

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
      taskId,
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
      taskId,
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
