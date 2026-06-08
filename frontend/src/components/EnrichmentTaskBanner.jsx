import { useEnrichmentTask } from '../state/EnrichmentTaskContext.jsx';

const STEP_LABELS = {
  summary: '摘要',
  recognition: '识别',
  rewrite: '改写',
};

/**
 * 顶部常驻的「加料进度」小卡片.
 *
 * 设计目标: 即便用户离开加料工作台, 仍然能看到当前进度并能一键取消.
 */
export function EnrichmentTaskBanner({ onJumpToWorkbench }) {
  const {
    running,
    novelTitle,
    aggregate,
    currentChapter,
    lastEvent,
    errorMessage,
    startTime,
    cancel,
    reset,
  } = useEnrichmentTask();

  // 没有正在跑 + 没有最近一次任务状态 -> 不渲染
  if (!running && !lastEvent) return null;

  const pct = aggregate.total > 0
    ? Math.round((aggregate.done / aggregate.total) * 100)
    : 0;

  const elapsed = startTime
    ? Math.max(0, Math.floor((Date.now() - startTime) / 1000))
    : 0;
  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const ss = String(elapsed % 60).padStart(2, '0');

  let stateClass = 'running';
  let stateLabel = '处理中';
  if (lastEvent === 'complete') {
    stateClass = 'done';
    stateLabel = '已完成';
  } else if (lastEvent === 'cancelled') {
    stateClass = 'cancelled';
    stateLabel = '已取消';
  } else if (lastEvent === 'error') {
    stateClass = 'error';
    stateLabel = '失败';
  }

  return (
    <div
      className={`enrichment-task-banner ${stateClass}`}
      onClick={() => onJumpToWorkbench?.()}
      role="status"
    >
      <div className="enrichment-task-banner-icon" aria-hidden>
        {stateClass === 'running' && <span className="enrichment-task-spinner" />}
        {stateClass === 'done' && (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="2">
            <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
        {stateClass === 'cancelled' && (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeLinecap="round" />
          </svg>
        )}
        {stateClass === 'error' && (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="2">
            <circle cx="12" cy="12" r="10" stroke="currentColor" />
            <path d="M12 8v4M12 16h.01" stroke="currentColor" strokeLinecap="round" />
          </svg>
        )}
      </div>
      <div className="enrichment-task-banner-main">
        <div className="enrichment-task-banner-title">
          {novelTitle ? `《${novelTitle}》` : '小说加料'} · {stateLabel}
          {running && (
            <span className="enrichment-task-banner-elapsed">{mm}:{ss}</span>
          )}
        </div>
        <div className="enrichment-task-banner-progress">
          <div className="enrichment-task-banner-track">
            <div
              className="enrichment-task-banner-bar"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="enrichment-task-banner-count">
            {aggregate.done}/{aggregate.total} ({pct}%)
          </span>
        </div>
        {currentChapter && running && (
          <div className="enrichment-task-banner-current">
            正在 {STEP_LABELS[currentChapter.step] || currentChapter.step}：
            第 {currentChapter.chapter_number} 章
            {currentChapter.title ? ` ${currentChapter.title}` : ''}
          </div>
        )}
        {stateClass === 'error' && errorMessage && (
          <div className="enrichment-task-banner-error">{errorMessage}</div>
        )}
      </div>
      <div className="enrichment-task-banner-actions" onClick={(e) => e.stopPropagation()}>
        {running ? (
          <button
            type="button"
            className="enrichment-task-banner-cancel"
            onClick={cancel}
            title="取消任务"
          >
            取消
          </button>
        ) : (
          <button
            type="button"
            className="enrichment-task-banner-close"
            onClick={reset}
            title="关闭通知"
          >
            关闭
          </button>
        )}
      </div>
    </div>
  );
}
