import { useEffect, useMemo, useState } from 'react';

const STATUS_DOTS = {
  pending: { label: '待处理', cls: 'dot-pending' },
  running: { label: '进行中', cls: 'dot-running' },
  done: { label: '已完成', cls: 'dot-done' },
  failed: { label: '失败', cls: 'dot-failed' },
  skipped: { label: '跳过', cls: 'dot-skipped' },
};
const statusLabel = (s) => (STATUS_DOTS[s] ? STATUS_DOTS[s].label : '待处理');
const statusCls = (s) => (STATUS_DOTS[s] ? STATUS_DOTS[s].cls : 'dot-pending');

function StatusRow({ summary, recognition, rewrite }) {
  return (
    <span className="enrichment-overview-status-row">
      <span className={`enrichment-overview-dot ${statusCls(summary)}`} title={`摘要: ${statusLabel(summary)}`} />
      <span className={`enrichment-overview-dot ${statusCls(recognition)}`} title={`识别: ${statusLabel(recognition)}`} />
      <span className={`enrichment-overview-dot ${statusCls(rewrite)}`} title={`改写: ${statusLabel(rewrite)}`} />
      <span className="enrichment-overview-status-hint">
        {statusLabel(summary)} / {statusLabel(recognition)} / {statusLabel(rewrite)}
      </span>
    </span>
  );
}

/**
 * AI加料「总览」: 章节列表 + 状态徽标 + "在阅读器打开" 入口.
 *
 * v0.3 设计: 不再在 workbench 内做单章加料 (旧的 3 列布局 + 重新生成按钮已全部移除);
 * 加料操作统一在 NovelReader 的 EnrichmentSidePanel 中完成.
 */
export function EnrichmentOverview({
  items = [],
  loading = false,
  onJumpToReading,
  onRetryFailed,
  onExport,
  onReset,
  busy = false,
  exporting = false,
}) {
  const [query, setQuery] = useState('');
  useEffect(() => {
    setQuery('');
  }, [items.length]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) =>
        String(it.chapter_number).includes(q) ||
        (it.title || '').toLowerCase().includes(q) ||
        (it.scene_tag || '').toLowerCase().includes(q)
    );
  }, [items, query]);

  // 顶部统计
  const total = items.length;
  const summaryDone = items.filter((it) => it.summary_status === 'done').length;
  const recognitionDone = items.filter((it) => it.recognition_status === 'done').length;
  const rewriteDone = items.filter((it) => it.rewrite_status === 'done').length;
  const applied = items.filter((it) => it.has_applied).length;
  const totalFailed = items.filter(
    (it) =>
      it.summary_status === 'failed' ||
      it.recognition_status === 'failed' ||
      it.rewrite_status === 'failed'
  ).length;

  return (
    <div className="enrichment-overview">
      <div className="enrichment-overview-stats">
        <div className="enrichment-overview-stat">
          <span className="enrichment-overview-stat-value">{total}</span>
          <span className="enrichment-overview-stat-label">章节</span>
        </div>
        <div className="enrichment-overview-stat">
          <span className="enrichment-overview-stat-value">{summaryDone}</span>
          <span className="enrichment-overview-stat-label">已总结</span>
        </div>
        <div className="enrichment-overview-stat">
          <span className="enrichment-overview-stat-value">{recognitionDone}</span>
          <span className="enrichment-overview-stat-label">已识别</span>
        </div>
        <div className="enrichment-overview-stat">
          <span className="enrichment-overview-stat-value">{rewriteDone}</span>
          <span className="enrichment-overview-stat-label">已改写</span>
        </div>
        <div className="enrichment-overview-stat highlight">
          <span className="enrichment-overview-stat-value">{applied}</span>
          <span className="enrichment-overview-stat-label">已应用</span>
        </div>
        {totalFailed > 0 && (
          <div className="enrichment-overview-stat danger">
            <span className="enrichment-overview-stat-value">{totalFailed}</span>
            <span className="enrichment-overview-stat-label">失败</span>
          </div>
        )}
      </div>

      <div className="enrichment-overview-tools">
        <label className="project-search-bar small">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
            <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" />
          </svg>
          <input
            type="text"
            placeholder="搜索章号 / 标题 / 场景"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="enrichment-overview-tools-actions">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!totalFailed || busy}
            onClick={onRetryFailed}
            title="重试所有失败章节"
          >
            {busy ? <span className="loading-spinner small" /> : null}
            重试失败
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!rewriteDone || exporting || busy}
            onClick={onExport}
          >
            {exporting ? <span className="loading-spinner small" /> : null}
            导出 TXT
          </button>
          <button
            type="button"
            className="btn btn-ghost danger"
            disabled={busy}
            onClick={onReset}
          >
            清空加料
          </button>
        </div>
      </div>

      {loading ? (
        <div className="library-list-loading">
          <div className="loading-spinner small" />
          <span>载入章节…</span>
        </div>
      ) : items.length === 0 ? (
        <div className="library-list-empty">
          暂无章节, 请先在「解析目录」中解析章节
        </div>
      ) : (
        <div className="enrichment-overview-table-wrap">
          <table className="enrichment-overview-table">
            <thead>
              <tr>
                <th style={{ width: 60 }}>#</th>
                <th>标题</th>
                <th style={{ width: 180 }}>状态</th>
                <th style={{ width: 110 }}>场景</th>
                <th style={{ width: 100 }}>已应用</th>
                <th style={{ width: 140 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((it) => (
                <tr key={it.chapter_id} className="enrichment-overview-row">
                  <td className="enrichment-overview-num">{it.chapter_number}</td>
                  <td className="enrichment-overview-title">
                    {it.title || '—'}
                  </td>
                  <td>
                    <StatusRow
                      summary={it.summary_status}
                      recognition={it.recognition_status}
                      rewrite={it.rewrite_status}
                    />
                  </td>
                  <td>
                    {it.scene_tag ? (
                      <span className="enrichment-overview-scene-tag">
                        {it.scene_tag}
                      </span>
                    ) : (
                      <span className="enrichment-overview-muted">—</span>
                    )}
                  </td>
                  <td>
                    {it.has_applied ? (
                      <span className="enrichment-overview-applied">✓</span>
                    ) : (
                      <span className="enrichment-overview-muted">—</span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost small"
                      onClick={() => onJumpToReading?.(it.chapter_id)}
                    >
                      阅读器打开 →
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && items.length > 0 && (
                <tr>
                  <td colSpan={6} className="enrichment-overview-empty">
                    没有匹配的章节
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
