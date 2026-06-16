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
import { useTaskPersist } from '../hooks/useTaskPersist.js';
import { getOrCreateClientId } from '../utils/clientId.js';

const CreationTaskContext = createContext(null);

// 修复 #23: 拆分为 3 个独立 Context, 减少无谓 re-render.
// - CreationTaskProgressContext  : 每帧都可能变的进度 (running/progress/lastEvent/errorMessage/startTime/version)
// - CreationTaskIdentityContext : 启动后基本不变的身份 (taskId/projectId/projectTitle/chapterNo/mirrorWarning)
// - CreationTaskControlContext  : 行为回调 (startGeneration/cancel/reset), 仅在 useCallback 重生成时变化
const CreationTaskProgressContext = createContext(null);
const CreationTaskIdentityContext = createContext(null);
const CreationTaskControlContext = createContext(null);

const STORAGE_KEY = 'ainovel.creation.task.v1';

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

/**
 * AI 小说创作 — 章节生成任务上下文.
 *
 * 与 EnrichmentTaskContext 几乎对称, 但承载的是"当前正在生成的项目 + 章节"
 * 状态. 关键点:
 *
 * * ``taskId`` 持久化到 localStorage, 刷新后询问后端, 重新挂 SSE 订阅.
 * * ``genProgress`` 同步持久化, 重连第一帧就有内容显示.
 * * 同 (project_id) 同时只允许 1 个生成任务 (后端 registry 层校验).
 * * 即使用户在 workbench / image 页面, 任务仍在后端跑, 进度不丢.
 */
export function CreationTaskProvider({ children }) {
  // UX-#11: 同步从 localStorage 读; 后端镜像在 mount-effect 中异步补
  const initial = useMemo(() => readPersisted() || {}, []);

  const [taskId, setTaskId] = useState(initial.taskId || null);
  const [running, setRunning] = useState(Boolean(initial.running));
  const [projectId, setProjectId] = useState(initial.projectId || null);
  const [projectTitle, setProjectTitle] = useState(initial.projectTitle || '');
  const [chapterNo, setChapterNo] = useState(initial.chapterNo || null);
  const [genProgress, setGenProgress] = useState(initial.genProgress || null);
  const [lastEvent, setLastEvent] = useState(initial.lastEvent || null);
  const [errorMessage, setErrorMessage] = useState(initial.errorMessage || '');
  const [startTime, setStartTime] = useState(initial.startTime || null);
  const [version, setVersion] = useState(0);

  const controllerRef = useRef(null);
  const isMountedRef = useRef(true);
  const clientId = useMemo(() => getOrCreateClientId(), []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, []);

  const persistedSnapshot = useMemo(() => {
    if (!running && !lastEvent) return null;
    return {
      taskId,
      running,
      projectId,
      projectTitle,
      chapterNo,
      genProgress,
      lastEvent,
      errorMessage,
      startTime,
    };
  }, [
    chapterNo,
    errorMessage,
    genProgress,
    lastEvent,
    projectId,
    projectTitle,
    running,
    startTime,
    taskId,
  ]);

  const applyExternalSnapshot = useCallback((snapshot) => {
    if (!snapshot || typeof snapshot !== 'object') return;
    if (snapshot.taskId && controllerRef.current && snapshot.taskId === taskId) return;
    setTaskId(snapshot.taskId || null);
    setRunning(Boolean(snapshot.running));
    setProjectId(snapshot.projectId || null);
    setProjectTitle(snapshot.projectTitle || '');
    setChapterNo(snapshot.chapterNo || null);
    setGenProgress(snapshot.genProgress || null);
    setLastEvent(snapshot.lastEvent || null);
    setErrorMessage(snapshot.errorMessage || '');
    setStartTime(snapshot.startTime || null);
  }, [taskId]);

  const { mirrorWarning, restoreMirror } = useTaskPersist({
    storageKey: STORAGE_KEY,
    snapshot: persistedSnapshot,
    onExternalSnapshot: applyExternalSnapshot,
    mirror: clientId
      ? {
          clientId,
          put: (id, snap) => api.tasks.putMirror(id, snap),
          get: (id) => api.tasks.getMirror(id),
        }
      : null,
  });

  // 处理业务事件, 维护 genProgress
  const handleEvent = useCallback((payload) => {
    if (!payload || !isMountedRef.current) return;
    const data = payload.data || {};
    // 兼容旧的事件结构: payload 本身可能就是 {event, ...}
    const ev = payload.event || data.event;
    if (ev === 'start' || ev === 'planner_done' || ev === 'title_generated' ||
        (ev && ev.startsWith('writer_')) || (ev && ev.startsWith('critic_')) ||
        ev === 'done' || ev === 'error' || ev === 'critic_rejected' ||
        ev === 'revision_start' || ev === 'bridge_done') {
      setGenProgress((prev) => {
        const next = { ...(prev || { stage: 'start', variants: {}, autoTitle: null }) };
        if (ev === 'start') {
          next.stage = 'start';
          next.chapter_id = data.chapter_id;
          next.variants = {};
          next.max_revise = data.max_revise;
          next.score_threshold = data.score_threshold;
          next.attempts = 0;
          next.attempt_scores = [];
          if (data.title) next.userTitle = data.title;
        } else if (ev === 'bridge_done') {
          next.bridge_score = data.bridge_score;
          next.bridge_conflicts = data.conflicts || [];
        } else if (ev === 'planner_done') {
          next.stage = 'planner_done';
          next.directions = data.directions || [];
          next.variant_ids = data.variant_ids || [];
          if (typeof data.attempt === 'number') {
            next.attempt = data.attempt;
          }
        } else if (ev === 'title_generated') {
          next.autoTitle = data.title;
        } else if (ev === 'revision_start') {
          next.stage = 'revision_start';
          next.attempt = data.attempt;
          next.max_attempts = data.max_attempts;
          next.previous_score = data.previous_score;
        } else if (ev && ev.startsWith('writer_')) {
          const idx = Number(ev.split('_')[1]);
          next.variants = {
            ...(next.variants || {}),
            [idx]: { state: 'critiquing', preview: data.preview, word_count: data.word_count },
          };
          next.stage = ev;
        } else if (ev && ev.startsWith('critic_')) {
          const idx = Number(ev.split('_')[1]);
          const prev = next.variants?.[idx] || {};
          next.variants = {
            ...(next.variants || {}),
            [idx]: {
              ...prev,
              state: data.passed ? 'done' : 'rejected',
              score: data.score,
              passed: data.passed,
              variant_id: data.variant_id,
              issues: data.issues || prev.issues,
              modifications: data.modifications || prev.modifications,
            },
          };
          next.stage = ev;
          // 累积每轮评分, 给前端展示评分曲线
          const attempt_scores = [...(next.attempt_scores || [])];
          if (typeof data.attempt === 'number') {
            attempt_scores.push({ attempt: data.attempt, score: data.score });
            next.attempt_scores = attempt_scores;
          }
        } else if (ev === 'critic_rejected') {
          // 整体没通过, 准备重做. 保留上轮分数, 给前端"重做中"提示.
          next.stage = 'critic_rejected';
          next.last_rejected = {
            attempt: data.attempt,
            score: data.score,
            threshold: data.threshold,
            issues: data.issues,
            modifications: data.modifications,
          };
        } else if (ev === 'done') {
          next.stage = 'done';
          next.chapter_id = data.chapter_id;
          if (data.title) next.autoTitle = data.title;
          next.final_score = data.final_score;
          next.accepted = data.accepted;
          next.attempts = data.attempts;
        } else if (ev === 'error') {
          next.stage = 'error';
          next.error = data.message || '生成失败';
        }
        return next;
      });
    }
    if (ev === 'done') {
      setLastEvent('complete');
      setRunning(false);
      setVersion((v) => v + 1);
    } else if (ev === 'cancelled') {
      setLastEvent('cancelled');
      setRunning(false);
      setVersion((v) => v + 1);
    } else if (ev === 'error') {
      setLastEvent('error');
      setErrorMessage(data.message || '生成失败');
      setRunning(false);
      setVersion((v) => v + 1);
    }
  }, []);

  /**
   * 启动新任务. ``onProgress(payload)`` 透传给调用方做 UI 同步.
   * ``onComplete()`` 在终态事件到达时调用一次.
   */
  const startGeneration = useCallback(
    ({
      targetProjectId,
      projectTitle: title,
      userIntent,
      chapterNo: cno,
      title: chapTitle,
      force = false,
      maxRevise = 2,
      scoreThreshold = 7.0,
      onProgress,
      onComplete,
    }) => {
      if (!targetProjectId) return;
      if (controllerRef.current) {
        try { controllerRef.current.abort(); } catch { /* noop */ }
        controllerRef.current = null;
      }
      const controller = new AbortController();
      controllerRef.current = controller;
      setRunning(true);
      setProjectId(targetProjectId);
      setProjectTitle(title || '');
      setChapterNo(cno);
      setLastEvent('start');
      setErrorMessage('');
      setStartTime(Date.now());
      setGenProgress({ stage: 'start', variants: {}, autoTitle: null });
      setVersion((v) => v + 1);

      const onEvent = (payload) => {
        if (!isMountedRef.current) return;
        if (payload && payload.event === 'registered' && payload.task_id) {
          setTaskId(payload.task_id);
          return;
        }
        handleEvent(payload);
        onProgress?.(payload);
        if (payload && (payload.event === 'done' || payload.event === 'cancelled' || payload.event === 'error')) {
          onComplete?.(payload);
        }
      };

      api.creation
        .generate(
          targetProjectId,
          {
            user_intent: userIntent,
            title: chapTitle,
            chapter_no: cno,
            force,
            max_revise: maxRevise,
            score_threshold: scoreThreshold,
          },
          { signal: controller.signal, onEvent }
        )
        .catch((err) => {
          if (!isMountedRef.current) return;
          if (err && (err.name === 'AbortError' || err.message === '请求已取消')) {
            setLastEvent('cancelled');
          } else {
            setLastEvent('error');
            setErrorMessage(err instanceof ApiError ? err.message : err?.message || '请求失败');
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
    if (taskId) {
      api.tasks.cancel(taskId).catch(() => { /* noop */ });
    }
  }, [taskId]);

  const reset = useCallback(() => {
    setRunning(false);
    setTaskId(null);
    setProjectId(null);
    setProjectTitle('');
    setChapterNo(null);
    setGenProgress(null);
    setLastEvent(null);
    setErrorMessage('');
    setStartTime(null);
  }, []);

  // mount 时尝试重连
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let activeController = null;
    // UX-#11: 优先尝试后端镜像, localStorage 没数据时也能恢复
    restoreMirror().then((snap) => {
      if (cancelled || !snap || !snap.taskId || snap.taskId === taskId) return;
      applyExternalSnapshot(snap);
    });
    (async () => {
      try {
        const rec = await api.tasks.get(taskId);
        if (cancelled) return;
        if (rec && !rec.done) {
          setRunning(true);
          setProjectId(rec.subject_id);
          setProjectTitle(rec.title || '');
          setChapterNo(rec.meta && rec.meta.chapter_no);
          setLastEvent('start');
          if (controllerRef.current) {
            try { controllerRef.current.abort(); } catch { /* noop */ }
          }
          const controller = new AbortController();
          controllerRef.current = controller;
          activeController = controller;

          getEventStream(api.tasks.subscribeUrl(rec.task_id), {
            signal: controller.signal,
            onEvent: (ev) => {
              if (ev && ev.event === 'subscribed') return;
              handleEvent(ev);
            },
          }).catch((err) => {
            if (!isMountedRef.current) return;
            if (err && (err.name === 'AbortError' || err.message === '请求已取消')) return;
            // eslint-disable-next-line no-console
            console.warn('Re-subscribe to creation task failed', err);
          });
        } else if (rec && rec.done) {
          if (rec.final_state) {
            setLastEvent(rec.final_state);
            setRunning(false);
          }
        } else {
          setTaskId(null);
        }
      } catch (err) {
        if (cancelled) return;
        if (err && err.status === 404) {
          setTaskId(null);
        }
      }
    })();
    return () => {
      cancelled = true;
      if (activeController) {
        try { activeController.abort(); } catch { /* noop */ }
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applyExternalSnapshot, restoreMirror, taskId]);

  const value = useMemo(
    () => ({
      taskId,
      running,
      projectId,
      projectTitle,
      chapterNo,
      genProgress,
      lastEvent,
      errorMessage,
      mirrorWarning,
      startTime,
      version,
      startGeneration,
      cancel,
      reset,
    }),
    [
      taskId, running, projectId, projectTitle, chapterNo,
      genProgress, lastEvent, errorMessage, mirrorWarning, startTime, version,
      startGeneration, cancel, reset,
    ]
  );

  // 修复 #23: progress / identity / control 三路独立 Provider.
  // 旧 ``useCreationTask`` 行为不变, 仍返回合并对象; 新 selector hook 见文末.
  const progressValue = useMemo(
    () => ({
      running,
      genProgress,
      lastEvent,
      errorMessage,
      startTime,
      version,
    }),
    [running, genProgress, lastEvent, errorMessage, startTime, version]
  );
  const identityValue = useMemo(
    () => ({ taskId, projectId, projectTitle, chapterNo, mirrorWarning }),
    [taskId, projectId, projectTitle, chapterNo, mirrorWarning]
  );
  const controlValue = useMemo(
    () => ({ startGeneration, cancel, reset }),
    [startGeneration, cancel, reset]
  );

  return (
    <CreationTaskContext.Provider value={value}>
      <CreationTaskProgressContext.Provider value={progressValue}>
        <CreationTaskIdentityContext.Provider value={identityValue}>
          <CreationTaskControlContext.Provider value={controlValue}>
            {children}
          </CreationTaskControlContext.Provider>
        </CreationTaskIdentityContext.Provider>
      </CreationTaskProgressContext.Provider>
    </CreationTaskContext.Provider>
  );
}

export function useCreationTask() {
  const ctx = useContext(CreationTaskContext);
  if (!ctx) {
    throw new Error('useCreationTask must be used inside CreationTaskProvider');
  }
  return ctx;
}

// 修复 #23: 细粒度 selector hook, 组件可以只订阅自己关心的字段.
function _orThrow(ctx, hookName) {
  if (!ctx) {
    throw new Error(`${hookName} must be used inside CreationTaskProvider`);
  }
  return ctx;
}

/** 只订阅"进度"相关字段, 每帧变化时 re-render. */
export function useTaskProgress() {
  return _orThrow(useContext(CreationTaskProgressContext), 'useTaskProgress');
}

/** 只订阅"任务身份"相关字段, 通常只在 startGeneration / 重连时变化. */
export function useTaskIdentity() {
  return _orThrow(useContext(CreationTaskIdentityContext), 'useTaskIdentity');
}

/** 只订阅"行为控制"回调, 引用稳定 (useCallback). */
export function useTaskControl() {
  return _orThrow(useContext(CreationTaskControlContext), 'useTaskControl');
}
