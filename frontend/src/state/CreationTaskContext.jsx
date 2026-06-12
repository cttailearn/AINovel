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

const CreationTaskContext = createContext(null);

const STORAGE_KEY = 'ainovel.creation.task.v1';
// UX-#11: 跨设备/重装恢复 — 用一个稳定的 client_id 关联
const CLIENT_ID_KEY = 'ainovel.client.id.v1';

function getOrCreateClientId() {
  if (typeof window === 'undefined') return null;
  let id = null;
  try {
    id = window.localStorage.getItem(CLIENT_ID_KEY);
    if (!id) {
      id = `cli_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
      window.localStorage.setItem(CLIENT_ID_KEY, id);
    }
  } catch { /* noop */ }
  return id;
}

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
  } catch { /* noop */ }
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

  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, []);

  // 持久化
  useEffect(() => {
    if (!running && !lastEvent) {
      writePersisted(null);
      return;
    }
    const snapshot = {
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
    writePersisted(snapshot);
    // UX-#11: 同时镜像到后端, 跨设备/重装可恢复
    const clientId = getOrCreateClientId();
    if (clientId) {
      api.tasks.putMirror(clientId, snapshot).catch(() => { /* 静默失败, 仍走 localStorage */ });
    }
  }, [
    taskId,
    running,
    projectId,
    projectTitle,
    chapterNo,
    genProgress,
    lastEvent,
    errorMessage,
    startTime,
  ]);

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
    writePersisted(null);
  }, []);

  // mount 时尝试重连
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let activeController = null;
    // UX-#11: 优先尝试后端镜像, localStorage 没数据时也能恢复
    const clientId = getOrCreateClientId();
    if (clientId) {
      api.tasks.getMirror(clientId).then((res) => {
        if (cancelled) return;
        if (res && res.snapshot && res.snapshot.taskId
            && res.snapshot.taskId !== taskId) {
          setTaskId(res.snapshot.taskId);
          setRunning(!!res.snapshot.running);
          setProjectId(res.snapshot.projectId || null);
          setProjectTitle(res.snapshot.projectTitle || '');
          setChapterNo(res.snapshot.chapterNo || null);
          setGenProgress(res.snapshot.genProgress || null);
          setLastEvent(res.snapshot.lastEvent || 'start');
          setErrorMessage(res.snapshot.errorMessage || '');
          setStartTime(res.snapshot.startTime || null);
        }
      }).catch(() => { /* 静默 */ });
    }
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
          writePersisted(null);
          setTaskId(null);
        }
      } catch (err) {
        if (cancelled) return;
        if (err && err.status === 404) {
          writePersisted(null);
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
  }, [taskId]);

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
      startTime,
      version,
      startGeneration,
      cancel,
      reset,
    }),
    [
      taskId, running, projectId, projectTitle, chapterNo,
      genProgress, lastEvent, errorMessage, startTime, version,
      startGeneration, cancel, reset,
    ]
  );

  return (
    <CreationTaskContext.Provider value={value}>
      {children}
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
