function StatCard({ value, label, tone }) {
  return (
    <div className={`enrichment-stat-card enrichment-stat-${tone || 'default'}`}>
      <div className="enrichment-stat-value">{value}</div>
      <div className="enrichment-stat-label">{label}</div>
    </div>
  );
}

export function ProgressSummary({
  progress,
  onRetryFailed,
  onExport,
  onReset,
  busy,
  mergeAvailable,
  exporting,
}) {
  if (!progress) {
    return (
      <div className="enrichment-progress-summary">
        <div className="enrichment-progress-empty">尚无进度数据</div>
      </div>
    );
  }
  const totalFailed =
    (progress.summary_failed || 0) +
    (progress.recognition_failed || 0) +
    (progress.rewrite_failed || 0);
  const percent = progress.overall_percent || 0;

  return (
    <div className="enrichment-progress-summary">
      <div className="enrichment-progress-stats">
        <StatCard value={totalFailed} label="失败" tone="danger" />
        <StatCard
          value={
            (progress.summary_done || 0) +
            (progress.recognition_done || 0) +
            (progress.rewrite_done || 0)
          }
          label="已完成 (3步合计)"
          tone="success"
        />
      </div>

      <div className="enrichment-progress-block">
        <div className="enrichment-progress-row">
          <span>总进度</span>
          <span>{percent}%</span>
        </div>
        <div className="enrichment-progress-track">
          <div
            className="enrichment-progress-bar"
            style={{ width: `${percent}%` }}
          />
        </div>
        <div className="enrichment-progress-row muted">
          <span>共 {progress.total || 0} 章</span>
        </div>
      </div>

      <div className="enrichment-progress-detail">
        <h4>分步进度</h4>
        <ul>
          <li>
            <span className="enrichment-progress-dot dot-done" />
            内容总结
            <span className="enrichment-progress-count">
              {progress.summary_done || 0}/{progress.total || 0}
            </span>
            {(progress.summary_failed || 0) > 0 && (
              <span className="enrichment-progress-failed">
                · 失败 {progress.summary_failed}
              </span>
            )}
          </li>
          <li>
            <span className="enrichment-progress-dot dot-done" />
            人物事件识别
            <span className="enrichment-progress-count">
              {progress.recognition_done || 0}/{progress.total || 0}
            </span>
            {(progress.recognition_failed || 0) > 0 && (
              <span className="enrichment-progress-failed">
                · 失败 {progress.recognition_failed}
              </span>
            )}
          </li>
          <li>
            <span className="enrichment-progress-dot dot-done" />
            AI 改写
            <span className="enrichment-progress-count">
              {progress.rewrite_done || 0}/{progress.total || 0}
            </span>
            {(progress.rewrite_failed || 0) > 0 && (
              <span className="enrichment-progress-failed">
                · 失败 {progress.rewrite_failed}
              </span>
            )}
          </li>
        </ul>
      </div>

      <div className="enrichment-progress-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!totalFailed || busy}
          onClick={onRetryFailed}
        >
          {busy ? <span className="loading-spinner small" /> : null}
          重试失败章节
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={!mergeAvailable || exporting || busy}
          onClick={onExport}
        >
          {exporting ? <span className="loading-spinner small" /> : null}
          下载加料版 TXT
        </button>
        <button
          type="button"
          className="btn btn-ghost danger"
          disabled={busy}
          onClick={onReset}
        >
          清空加料结果
        </button>
      </div>
    </div>
  );
}