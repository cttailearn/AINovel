import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';
import { ConfirmDialog } from './Modal/ConfirmDialog.jsx';
import { SplitView } from './enrichment/SplitView.jsx';
import { SummaryView } from './enrichment/SummaryView.jsx';
import { EnrichmentOverview } from './enrichment/EnrichmentOverview.jsx';
import { useEnrichmentTask } from '../state/EnrichmentTaskContext.jsx';

const STEPS = ['summary', 'recognition', 'rewrite'];

function pickEnabledModelId(models) {
  const enabled = (models || []).filter(
    (m) => m.enabled && (m.capability || 'chat') === 'chat'
  );
  return enabled[0]?.id || null;
}

/**
 * AI 加料调度中心 (v0.3 重构).
 *
 * 设计变更:
 * - 删除 3 列布局 (ChapterNav + ChapterDetail + ProgressSummary) -- 旧版 UI
 * - 删除 5 步 StepBar5 -- 旧版进度条
 * - 删除 ChapterDetail 内的 step 重新生成按钮 -- 旧版, 已迁到阅读器
 * - 新版: 调度中心只承担"批量管理 + 总览"职责, 单章加料操作统一在阅读器 EnrichmentSidePanel 完成
 *
 * 视图: 总览 (新) / 拆分 / 总结
 */
export function EnrichmentWorkbench({
  novelId,
  novel,
  models,
  onGoToSettings,
  onJumpToParse,
  onJumpToReading,
}) {
  const toast = useToast();
  const task = useEnrichmentTask();
  const [progress, setProgress] = useState(null);
  const [progressLoading, setProgressLoading] = useState(true);
  const [selfModels, setSelfModels] = useState([]);
  const effectiveModels = (models && models.length > 0) ? models : selfModels;
  const [selectedModelId, setSelectedModelId] = useState(() =>
    pickEnabledModelId(effectiveModels)
  );
  const [stepSelections, setStepSelections] = useState({
    summary: true,
    recognition: true,
    rewrite: true,
  });
  const [activeView, setActiveView] = useState('overview');
  const [exporting, setExporting] = useState(false);
  const [pendingReset, setPendingReset] = useState(false);
  const [concurrency, setConcurrency] = useState(2);
  const [reloadKey, setReloadKey] = useState(0);

  const batchRunning = task.running && task.novelId === novelId;
  const stepProgress = task.stepProgress;
  const lastEvent = task.lastEvent;
  const errorMessage = task.errorMessage;

  // 父级没传 models 时, 自取一次
  useEffect(() => {
    if (models && models.length > 0) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api.models.list();
        if (!cancelled) setSelfModels(data.configs || []);
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载模型失败');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadProgress = async () => {
    setProgressLoading(true);
    try {
      const data = await api.enrichment.listProgress(novelId);
      setProgress(data);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '加载进度失败');
    } finally {
      setProgressLoading(false);
    }
  };

  useEffect(() => {
    loadProgress();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelId]);

  // 任务状态变化时同步
  useEffect(() => {
    if (task.novelId !== novelId) return;
    if (lastEvent === 'complete') {
      loadProgress();
      setReloadKey((k) => k + 1);
      toast.success('批量处理完成');
    } else if (lastEvent === 'error') {
      loadProgress();
      toast.error(`批量失败: ${errorMessage || '未知错误'}`);
    } else if (lastEvent === 'cancelled') {
      loadProgress();
      toast.info('已取消批量处理');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task.version, lastEvent]);

  // 模型列表变化时, 修正 selectedModelId
  useEffect(() => {
    if (selectedModelId) {
      const stillValid = (effectiveModels || []).some(
        (m) => m.id === selectedModelId && m.enabled && (m.capability || 'chat') === 'chat'
      );
      if (stillValid) return;
    }
    setSelectedModelId(pickEnabledModelId(effectiveModels));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveModels]);

  // 批量跑整本
  const handleBatch = () => {
    if (!selectedModelId) {
      toast.error('请先选择可用的 chat 模型');
      return;
    }
    const steps = STEPS.filter((s) => stepSelections[s]);
    if (steps.length === 0) {
      toast.error('请至少选择 1 个步骤');
      return;
    }
    task.startBatch({
      targetNovelId: novelId,
      novelTitle: novel?.title || '',
      modelConfigId: selectedModelId,
      steps,
      concurrency,
      skipExisting: true,
    });
  };

  const handleCancelBatch = () => task.cancel();

  // 重试失败
  const handleRetryFailed = async () => {
    if (!selectedModelId) {
      toast.error('请先选择可用的 chat 模型');
      return;
    }
    try {
      await api.enrichment.retryFailed(novelId);
      const failedIds = (progress?.items || []).filter(
        (it) =>
          it.summary_status === 'failed' ||
          it.recognition_status === 'failed' ||
          it.rewrite_status === 'failed'
      ).map((it) => it.chapter_id);
      if (failedIds.length === 0) {
        toast.info('没有失败章节');
        return;
      }
      const steps = STEPS.filter((s) => stepSelections[s]);
      if (steps.length === 0) {
        toast.error('请至少选择 1 个步骤');
        return;
      }
      toast.info(`已重置 ${failedIds.length} 个章节状态, 重新入队`);
      task.startBatch({
        targetNovelId: novelId,
        novelTitle: novel?.title || '',
        modelConfigId: selectedModelId,
        steps,
        chapterIds: failedIds,
        concurrency,
        skipExisting: false,
      });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '重试失败');
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
  const confirmReset = async () => {
    setPendingReset(false);
    try {
      await api.enrichment.reset(novelId);
      toast.success('已清空');
      await loadProgress();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '清空失败');
    }
  };

  // 视图
  const chatModels = (effectiveModels || []).filter(
    (m) => (m.capability || 'chat') === 'chat'
  );
  const enabledChatModels = chatModels.filter((m) => m.enabled);
  const overallDone = progress?.overall_percent || 0;

  // 视图切换后, 触发子视图刷新
  const handleViewChange = (k) => {
    setActiveView(k);
    if (k === 'overview' || k === 'summary') {
      setReloadKey((kk) => kk + 1);
    }
  };

  const items = progress?.items || [];

  const viewButtonClass = (k) =>
    `enrichment-view-tab ${activeView === k ? 'active' : ''}`;

  return (
    <div className="enrichment-workbench-v2">
      <div className="enrichment-wb2-header">
        <nav className="enrichment-wb2-tabs" aria-label="AI 加料视图">
          {[
            { k: 'overview', label: '总览' },
            { k: 'split', label: '拆分' },
            { k: 'summary', label: '总结' },
          ].map((t) => (
            <button
              key={t.k}
              type="button"
              className={viewButtonClass(t.k)}
              onClick={() => handleViewChange(t.k)}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="enrichment-wb2-actions">
          <div className="enrichment-wb2-field">
            <label>模型</label>
            <select
              value={selectedModelId || ''}
              onChange={(e) => setSelectedModelId(Number(e.target.value) || null)}
              disabled={batchRunning}
            >
              {chatModels.length === 0 ? (
                <option value="">(无可用模型, 请先在「系统设置」中添加)</option>
              ) : (
                <>
                  {enabledChatModels.length > 0 && (
                    <optgroup label="已启用">
                      {enabledChatModels.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {chatModels.some((m) => !m.enabled) && (
                    <optgroup label="已禁用">
                      {chatModels.filter((m) => !m.enabled).map((m) => (
                        <option key={m.id} value={m.id} disabled>
                          {m.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </>
              )}
            </select>
            {chatModels.length === 0 && (
              <button
                type="button"
                className="enrichment-wb2-link"
                onClick={() => onGoToSettings?.()}
              >
                去添加 →
              </button>
            )}
          </div>
          <div className="enrichment-wb2-field narrow">
            <label htmlFor="enrichment-concurrency">并发</label>
            <input
              id="enrichment-concurrency"
              type="number"
              min={1}
              max={8}
              step={1}
              value={concurrency}
              disabled={batchRunning}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (Number.isNaN(v)) return;
                setConcurrency(Math.max(1, Math.min(8, v)));
              }}
            />
          </div>
          <div className="enrichment-wb2-field checks">
            {STEPS.map((s) => (
              <label key={s} className="enrichment-wb2-check">
                <input
                  type="checkbox"
                  checked={stepSelections[s]}
                  onChange={(e) =>
                    setStepSelections((prev) => ({ ...prev, [s]: e.target.checked }))
                  }
                  disabled={batchRunning}
                />
                <span>
                  {s === 'summary' ? '总结' : s === 'recognition' ? '识别' : '改写'}
                </span>
              </label>
            ))}
          </div>
          {batchRunning ? (
            <button type="button" className="btn btn-ghost" onClick={handleCancelBatch}>
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
              开始批量处理
            </button>
          )}
        </div>
      </div>

      {batchRunning && stepProgress && (
        <div className="enrichment-wb2-progress">
          {STEPS.map((s) => {
            const sp = stepProgress[s] || { done: 0, total: 0 };
            const pct = sp.total > 0 ? Math.round((sp.done / sp.total) * 100) : 0;
            return (
              <div key={s} className="enrichment-wb2-progress-row">
                <span className="enrichment-wb2-progress-label">
                  {s === 'summary' ? '总结' : s === 'recognition' ? '识别' : '改写'}
                </span>
                <div className="enrichment-wb2-progress-track">
                  <div
                    className="enrichment-wb2-progress-bar"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="enrichment-wb2-progress-count">
                  {sp.done}/{sp.total}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <div className="enrichment-wb2-body">
        {activeView === 'overview' && (
          <EnrichmentOverview
            items={items}
            loading={progressLoading}
            onJumpToReading={onJumpToReading}
            onRetryFailed={handleRetryFailed}
            onExport={handleExport}
            onReset={() => setPendingReset(true)}
            busy={batchRunning}
            exporting={exporting}
          />
        )}

        {activeView === 'split' && (
          <SplitView
            novel={novel}
            onJumpToParse={() => onJumpToParse?.()}
            onJumpToChapter={(chapterId) => onJumpToReading?.(chapterId)}
          />
        )}

        {activeView === 'summary' && (
          <SummaryView
            key={`summary-${reloadKey}`}
            novel={novel}
            models={effectiveModels}
            selectedModelId={selectedModelId}
            onModelChange={setSelectedModelId}
            batchRunning={batchRunning}
            onRunBatch={(steps) => {
              const useSteps = steps && steps.length > 0 ? steps : ['summary'];
              if (!selectedModelId) {
                toast.error('请先选择可用的 chat 模型');
                return;
              }
              task.startBatch({
                targetNovelId: novelId,
                novelTitle: novel?.title || '',
                modelConfigId: selectedModelId,
                steps: useSteps,
                concurrency,
                skipExisting: true,
              });
            }}
            progress={progress}
            reloadKey={reloadKey}
          />
        )}
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
