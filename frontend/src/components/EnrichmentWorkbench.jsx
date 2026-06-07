import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';
import { ConfirmDialog } from './Modal/ConfirmDialog.jsx';
import { ChapterNav } from './enrichment/ChapterNav.jsx';
import { ChapterDetail } from './enrichment/ChapterDetail.jsx';
import { ProgressSummary } from './enrichment/ProgressSummary.jsx';
import { StepBar5 } from './enrichment/StepBar5.jsx';

const STEPS = ['summary', 'recognition', 'rewrite'];

function pickEnabledModelId(models) {
  const enabled = (models || []).filter((m) => m.enabled && (m.capability || 'chat') === 'chat');
  return enabled[0]?.id || null;
}

function mergeStepProgress(prev, incoming) {
  if (!incoming) return prev;
  const next = { ...(prev || {}) };
  Object.keys(incoming).forEach((step) => {
    if (!STEPS.includes(step)) return;
    next[step] = { ...(next[step] || {}), ...incoming[step] };
  });
  return next;
}

export function EnrichmentWorkbench({ novelId, novel, models, onProgressChange }) {
  const toast = useToast();
  const [progress, setProgress] = useState(null);
  const [progressLoading, setProgressLoading] = useState(true);
  const [selectedChapterId, setSelectedChapterId] = useState(null);
  const [chapterDetail, setChapterDetail] = useState(null);
  const [chapterDetailLoading, setChapterDetailLoading] = useState(false);
  const [selectedModelId, setSelectedModelId] = useState(() => pickEnabledModelId(models));
  const [stepSelections, setStepSelections] = useState({
    summary: true,
    recognition: true,
    rewrite: true,
  });
  const [batchRunning, setBatchRunning] = useState(false);
  const [stepProgress, setStepProgress] = useState(null);
  const [runningStep, setRunningStep] = useState(null);
  const [runningAll, setRunningAll] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [pendingReset, setPendingReset] = useState(false);
  const batchAbortRef = useRef(null);
  const navListRef = useRef(null);

  // 拉取进度
  const loadProgress = async () => {
    setProgressLoading(true);
    try {
      const data = await api.enrichment.listProgress(novelId);
      setProgress(data);
      if (!selectedChapterId && data.items && data.items.length > 0) {
        setSelectedChapterId(data.items[0].chapter_id);
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '加载进度失败');
    } finally {
      setProgressLoading(false);
    }
  };

  useEffect(() => {
    loadProgress();
    setStepProgress(null);
    setSelectedChapterId(null);
    setChapterDetail(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelId]);

  // 模型列表变化时若当前未选或不可用, 自动选第一个
  useEffect(() => {
    if (selectedModelId) {
      const stillValid = (models || []).some(
        (m) => m.id === selectedModelId && m.enabled
      );
      if (stillValid) return;
    }
    setSelectedModelId(pickEnabledModelId(models));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [models]);

  // 拉取章节详情
  useEffect(() => {
    if (!selectedChapterId) {
      setChapterDetail(null);
      return;
    }
    let cancelled = false;
    setChapterDetailLoading(true);
    (async () => {
      try {
        const data = await api.enrichment.getDetail(selectedChapterId);
        if (!cancelled) setChapterDetail(data);
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载章节详情失败');
        }
      } finally {
        if (!cancelled) setChapterDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedChapterId, toast]);

  const mergeItemIntoProgress = (chapterId, step, status) => {
    setProgress((prev) => {
      if (!prev) return prev;
      const items = (prev.items || []).map((it) => {
        if (it.chapter_id !== chapterId) return it;
        const next = { ...it, [`${step}_status`]: status };
        const ss = next.summary_status;
        const rs = next.recognition_status;
        const ws = next.rewrite_status;
        let overall = 'pending';
        if (ss === 'running' || rs === 'running' || ws === 'running') overall = 'running';
        else if (ss === 'done' && rs === 'done' && ws === 'done') overall = 'done';
        else if (
          (ss === 'failed' || rs === 'failed' || ws === 'failed') &&
          !['running', 'pending'].includes(ss) &&
          !['running', 'pending'].includes(rs) &&
          !['running', 'pending'].includes(ws)
        )
          overall = 'partial';
        return { ...next, status: overall };
      });
      return { ...prev, items };
    });
  };

  // 单章单步
  const handleRegenerateStep = async (step, opts = {}) => {
    if (!selectedChapterId) {
      toast.error('请先选择章节');
      return;
    }
    if (!selectedModelId) {
      toast.error('请先选择可用的 chat 模型');
      return;
    }
    const fnMap = {
      summary: api.enrichment.runSummary,
      recognition: api.enrichment.runRecognition,
      rewrite: api.enrichment.runRewrite,
    };
    setRunningStep(step);
    mergeItemIntoProgress(selectedChapterId, step, 'running');
    try {
      // 手动保存优先
      if (opts.manualSummary !== undefined) {
        await api.enrichment.updateDetail(selectedChapterId, {
          summary: opts.manualSummary,
        });
        mergeItemIntoProgress(selectedChapterId, step, 'done');
        const fresh = await api.enrichment.getDetail(selectedChapterId);
        setChapterDetail(fresh);
        onProgressChange?.();
        toast.success('摘要已保存');
        return;
      }
      if (opts.manualRewrite !== undefined) {
        await api.enrichment.updateDetail(selectedChapterId, {
          rewrite_text: opts.manualRewrite,
        });
        mergeItemIntoProgress(selectedChapterId, step, 'done');
        const fresh = await api.enrichment.getDetail(selectedChapterId);
        setChapterDetail(fresh);
        onProgressChange?.();
        toast.success('改写正文已保存');
        return;
      }
      await fnMap[step](selectedChapterId, { model_config_id: selectedModelId });
      const fresh = await api.enrichment.getDetail(selectedChapterId);
      setChapterDetail(fresh);
      const status = fresh[`${step}_status`];
      if (status === 'done') {
        toast.success(`${step} 完成`);
      } else if (status === 'failed') {
        toast.error(`${step} 失败: ${fresh[`${step}_error`] || '未知错误'}`);
      }
      mergeItemIntoProgress(selectedChapterId, step, status);
      onProgressChange?.();
    } catch (err) {
      mergeItemIntoProgress(selectedChapterId, step, 'failed');
      toast.error(err instanceof ApiError ? err.message : '执行失败');
    } finally {
      setRunningStep(null);
    }
  };

  // 一键重跑本章节 (3 步全跑)
  const handleRegenerateAll = async () => {
    if (!selectedChapterId) {
      toast.error('请先选择章节');
      return;
    }
    if (!selectedModelId) {
      toast.error('请先选择可用的 chat 模型');
      return;
    }
    setRunningAll(true);
    try {
      for (const step of STEPS) {
        mergeItemIntoProgress(selectedChapterId, step, 'running');
        const fnMap = {
          summary: api.enrichment.runSummary,
          recognition: api.enrichment.runRecognition,
          rewrite: api.enrichment.runRewrite,
        };
        try {
          await fnMap[step](selectedChapterId, { model_config_id: selectedModelId });
          const fresh = await api.enrichment.getDetail(selectedChapterId);
          setChapterDetail(fresh);
          mergeItemIntoProgress(selectedChapterId, step, fresh[`${step}_status`] || 'failed');
        } catch (err) {
          mergeItemIntoProgress(selectedChapterId, step, 'failed');
          toast.error(`${step} 失败: ${err instanceof ApiError ? err.message : '未知错误'}`);
        }
      }
      onProgressChange?.();
    } finally {
      setRunningAll(false);
    }
  };

  // 批量跑整本
  const handleBatch = async () => {
    if (!selectedModelId) {
      toast.error('请先选择可用的 chat 模型');
      return;
    }
    const steps = STEPS.filter((s) => stepSelections[s]);
    if (steps.length === 0) {
      toast.error('请至少选择 1 个步骤');
      return;
    }
    if (batchAbortRef.current) {
      batchAbortRef.current.abort();
    }
    const controller = new AbortController();
    batchAbortRef.current = controller;
    setBatchRunning(true);
    setStepProgress({ summary: { done: 0, total: progress?.total || 0 } });

    try {
      await api.enrichment.batch(
        novelId,
        {
          model_config_id: selectedModelId,
          steps,
          concurrency: 2,
          skip_existing: true,
        },
        {
          signal: controller.signal,
          onEvent: (payload) => {
            if (!payload) return;
            if (payload.event === 'start') {
              setStepProgress(payload.step_progress || null);
            } else if (payload.event === 'step_start') {
              // 简单提示
            } else if (payload.event === 'chapter_start') {
              // 可扩展 toast
            } else if (payload.event === 'chapter_done' || payload.event === 'skip') {
              setStepProgress((prev) => mergeStepProgress(prev, payload.step_progress));
              const sid = payload.chapter_id;
              if (sid && payload.event === 'chapter_done') {
                mergeItemIntoProgress(sid, payload.step, payload.success ? 'done' : 'failed');
              }
            } else if (payload.event === 'step_done') {
              setStepProgress((prev) =>
                mergeStepProgress(prev, {
                  [payload.step]: { done: payload.done, total: payload.total },
                })
              );
            } else if (payload.event === 'complete') {
              toast.success('批量处理完成');
              loadProgress();
              if (selectedChapterId) {
                api.enrichment
                  .getDetail(selectedChapterId)
                  .then((d) => setChapterDetail(d))
                  .catch(() => {});
              }
              onProgressChange?.();
            } else if (payload.event === 'error') {
              toast.error(`批量失败: ${payload.message || '未知错误'}`);
            } else if (payload.event === 'cancelled') {
              toast.info('已取消');
            }
          },
        }
      );
    } catch (err) {
      if (err && err.name === 'AbortError') {
        toast.info('已取消批量处理');
      } else {
        toast.error(err instanceof ApiError ? err.message : '批量处理失败');
      }
    } finally {
      setBatchRunning(false);
      batchAbortRef.current = null;
      loadProgress();
    }
  };

  const handleCancelBatch = () => {
    if (batchAbortRef.current) {
      batchAbortRef.current.abort();
    }
  };

  // 重试失败章节
  const handleRetryFailed = async () => {
    if (!selectedModelId) {
      toast.error('请先选择可用的 chat 模型');
      return;
    }
    try {
      await api.enrichment.retryFailed(novelId);
      // 取出所有失败章节, 触发一次 batch
      const failedIds = (progress?.items || []).filter((it) => {
        const s = it.summary_status === 'failed';
        const r = it.recognition_status === 'failed';
        const w = it.rewrite_status === 'failed';
        return s || r || w;
      }).map((it) => it.chapter_id);
      if (failedIds.length === 0) {
        toast.info('没有失败章节');
        return;
      }
      toast.info(`已重置 ${failedIds.length} 个章节状态, 重新入队`);
      const steps = STEPS.filter((s) => stepSelections[s]);
      if (steps.length === 0) {
        toast.error('请至少选择 1 个步骤');
        return;
      }
      // 复用 batch 逻辑, 传 chapter_ids
      if (batchAbortRef.current) batchAbortRef.current.abort();
      const controller = new AbortController();
      batchAbortRef.current = controller;
      setBatchRunning(true);
      await api.enrichment.batch(
        novelId,
        {
          model_config_id: selectedModelId,
          steps,
          chapter_ids: failedIds,
          concurrency: 2,
          skip_existing: false,
        },
        {
          signal: controller.signal,
          onEvent: (payload) => {
            if (!payload) return;
            if (payload.event === 'chapter_done' || payload.event === 'skip') {
              setStepProgress((prev) => mergeStepProgress(prev, payload.step_progress));
              if (payload.event === 'chapter_done') {
                mergeItemIntoProgress(payload.chapter_id, payload.step, payload.success ? 'done' : 'failed');
              }
            } else if (payload.event === 'step_done') {
              setStepProgress((prev) =>
                mergeStepProgress(prev, {
                  [payload.step]: { done: payload.done, total: payload.total },
                })
              );
            } else if (payload.event === 'complete') {
              toast.success('重试完成');
              loadProgress();
              onProgressChange?.();
            } else if (payload.event === 'error') {
              toast.error(`重试失败: ${payload.message || '未知错误'}`);
            }
          },
        }
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '重试失败');
    } finally {
      setBatchRunning(false);
      batchAbortRef.current = null;
      loadProgress();
    }
  };

  // 导出
  const handleExport = async () => {
    setExporting(true);
    try {
      const url = api.enrichment.exportUrl(novelId);
      const response = await fetch(url, { method: 'GET' });
      if (!response.ok) {
        const text = await response.text();
        throw new ApiError(text || `导出失败 (${response.status})`, response.status, null);
      }
      const blob = await response.blob();
      const cd = response.headers.get('content-disposition') || '';
      const m = /filename="?([^"]+)"?/.exec(cd);
      const filename = (m && m[1]) || `${novel?.title || 'novel'}.enriched.txt`;
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(objectUrl);
      toast.success(`已下载: ${filename}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '导出失败');
    } finally {
      setExporting(false);
    }
  };

  // 重置
  const handleReset = async () => {
    setPendingReset(true);
  };

  const confirmReset = async () => {
    setPendingReset(false);
    try {
      await api.enrichment.reset(novelId);
      toast.success('已清空');
      setSelectedChapterId(null);
      setChapterDetail(null);
      loadProgress();
      onProgressChange?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '清空失败');
    }
  };

  // 视图
  const chatModels = (models || []).filter(
    (m) => (m.capability || 'chat') === 'chat'
  );
  const overallDone = progress?.overall_percent || 0;
  const mergeAvailable = (progress?.rewrite_done || 0) > 0;

  // 选中行滚动到视图
  const navScrollRef = useRef(null);
  useEffect(() => {
    if (!selectedChapterId || !navScrollRef.current) return;
    const node = navScrollRef.current.querySelector(
      `.enrichment-chapter-row.active`
    );
    if (node && node.scrollIntoView) {
      node.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedChapterId]);

  const items = progress?.items || [];

  const summaryState = useMemo(() => {
    if (!progress) return 'todo';
    if (progress.summary_done > 0 && progress.summary_done < progress.total)
      return 'partial';
    if (progress.summary_done === progress.total && progress.total > 0)
      return 'done';
    return 'todo';
  }, [progress]);
  const recognitionState = useMemo(() => {
    if (!progress) return 'todo';
    if (
      progress.recognition_done > 0 &&
      progress.recognition_done < progress.total
    )
      return 'partial';
    if (progress.recognition_done === progress.total && progress.total > 0)
      return 'done';
    return 'todo';
  }, [progress]);
  const rewriteState = useMemo(() => {
    if (!progress) return 'todo';
    if (progress.rewrite_done > 0 && progress.rewrite_done < progress.total)
      return 'partial';
    if (progress.rewrite_done === progress.total && progress.total > 0)
      return 'done';
    return 'todo';
  }, [progress]);
  const mergeState = overallDone >= 99.5 ? 'done' : 'todo';

  return (
    <div className="enrichment-workbench">
      <header className="enrichment-workbench-head">
        <div className="enrichment-workbench-title">
          <h2>{novel?.title || '加料工作台'}</h2>
          {novel?.author && <p>作者：{novel.author}</p>}
        </div>
        <div className="enrichment-workbench-actions">
          <div className="enrichment-workbench-model">
            <label>模型</label>
            <select
              value={selectedModelId || ''}
              onChange={(e) => setSelectedModelId(Number(e.target.value) || null)}
              disabled={batchRunning}
            >
              {chatModels.length === 0 ? (
                <option value="">(无可用模型，请先在「系统设置」中添加)</option>
              ) : (
                chatModels.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.enabled}>
                    {m.name} {m.enabled ? '' : '(已禁用)'}
                  </option>
                ))
              )}
            </select>
          </div>
          <div className="enrichment-workbench-steps">
            {STEPS.map((s) => (
              <label key={s} className="enrichment-workbench-step-check">
                <input
                  type="checkbox"
                  checked={stepSelections[s]}
                  onChange={(e) =>
                    setStepSelections((prev) => ({ ...prev, [s]: e.target.checked }))
                  }
                  disabled={batchRunning}
                />
                <span>
                  {s === 'summary' ? '内容总结' : s === 'recognition' ? '识别' : '改写'}
                </span>
              </label>
            ))}
          </div>
          {batchRunning ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={handleCancelBatch}
            >
              取消
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleBatch}
              disabled={chatModels.length === 0}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <polygon points="5 3 19 12 5 21 5 3" stroke="currentColor" strokeWidth="2" />
              </svg>
              开始处理
            </button>
          )}
        </div>
      </header>

      <StepBar5
        splitDone={Boolean((novel?.chapter_count || 0) > 0)}
        summaryDone={summaryState}
        recognitionDone={recognitionState}
        rewriteDone={rewriteState}
        mergeDone={mergeState}
      />

      {batchRunning && stepProgress && (
        <div className="enrichment-batch-progress">
          {STEPS.map((s) => {
            const sp = stepProgress[s] || { done: 0, total: 0 };
            const pct = sp.total > 0 ? Math.round((sp.done / sp.total) * 100) : 0;
            return (
              <div key={s} className="enrichment-batch-progress-row">
                <span className="enrichment-batch-progress-label">
                  {s === 'summary' ? '内容总结' : s === 'recognition' ? '识别' : '改写'}
                </span>
                <div className="enrichment-batch-progress-track">
                  <div
                    className="enrichment-batch-progress-bar"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="enrichment-batch-progress-count">
                  {sp.done}/{sp.total}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <div className="enrichment-workbench-grid">
        <div className="enrichment-workbench-col enrichment-workbench-col-left" ref={navScrollRef}>
          <ChapterNav
            items={items}
            selectedId={selectedChapterId}
            onSelect={setSelectedChapterId}
            loading={progressLoading}
            onJumpTop={() => {
              if (items[0]) setSelectedChapterId(items[0].chapter_id);
            }}
            onJumpBottom={() => {
              if (items.length > 0)
                setSelectedChapterId(items[items.length - 1].chapter_id);
            }}
          />
        </div>

        <div className="enrichment-workbench-col enrichment-workbench-col-center">
          <ChapterDetail
            detail={chapterDetail}
            loading={chapterDetailLoading}
            runningStep={runningStep}
            runningAll={runningAll}
            onRegenerateStep={handleRegenerateStep}
            onRegenerateAll={handleRegenerateAll}
          />
        </div>

        <div className="enrichment-workbench-col enrichment-workbench-col-right">
          <ProgressSummary
            progress={progress}
            busy={batchRunning || runningAll}
            mergeAvailable={mergeAvailable}
            exporting={exporting}
            onRetryFailed={handleRetryFailed}
            onExport={handleExport}
            onReset={handleReset}
          />
        </div>
      </div>

      <ConfirmDialog
        open={pendingReset}
        title="清空加料结果"
        message="将删除该书所有章节的摘要、识别、改写结果。原文与章节保留。"
        confirmText="清空"
        danger
        onCancel={() => setPendingReset(false)}
        onConfirm={confirmReset}
      />
    </div>
  );
}