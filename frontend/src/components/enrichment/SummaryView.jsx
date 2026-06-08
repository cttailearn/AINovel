import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../../api/client.js';
import { useToast } from '../Toast/ToastProvider.jsx';

const STATUS_DOTS = {
  pending: { label: '待处理', cls: 'dot-pending' },
  running: { label: '进行中', cls: 'dot-running' },
  done: { label: '已完成', cls: 'dot-done' },
  failed: { label: '失败', cls: 'dot-failed' },
};

function StatusDot({ status, label }) {
  const meta = STATUS_DOTS[status] || STATUS_DOTS.pending;
  return (
    <span
      className={`chapter-dot ${meta.cls}`}
      title={`${label}: ${meta.label}`}
    />
  );
}

function truncate(text, limit = 80) {
  if (!text) return '';
  const t = String(text).replace(/\s+/g, ' ').trim();
  return t.length <= limit ? t : `${t.slice(0, limit)}…`;
}

/**
 * 总结专属子页. 表格化展示所有章节的摘要状态 + 场景标签 + 登场人物数 / 关键事件数.
 * - 顶部: 模型下拉 + 步骤复选 + 批量重跑 (委托给 EnrichmentWorkbench)
 * - 行点击: 抽屉显示完整摘要 + 人物 + 事件
 */
export function SummaryView({
  novel,
  models,
  selectedModelId,
  onModelChange,
  batchRunning,
  onRunBatch,
  progress,
  reloadKey,
}) {
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const items = progress?.items || [];

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((it) => {
      if (statusFilter !== 'all' && it.summary_status !== statusFilter) {
        return false;
      }
      if (!q) return true;
      return (
        String(it.chapter_number).includes(q) ||
        (it.title || '').toLowerCase().includes(q) ||
        (it.scene_tag || '').toLowerCase().includes(q)
      );
    });
  }, [items, query, statusFilter]);

  // 打开行 → 拉详情
  useEffect(() => {
    if (!openId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    (async () => {
      try {
        const data = await api.enrichment.getDetail(openId);
        if (!cancelled) setDetail(data);
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载详情失败');
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [openId, reloadKey, toast]);

  const summaryCount = progress?.summary_done || 0;
  const total = progress?.total || 0;

  return (
    <div className="enrichment-summary-view">
      <header className="enrichment-summary-view-head">
        <div>
          <h3>章节总结</h3>
          <p>
            已完成 {summaryCount} / {total} 章 ·
            选中模型 {models?.find((m) => m.id === selectedModelId)?.name || '—'}
          </p>
        </div>
        <div className="enrichment-summary-view-tools">
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
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="enrichment-summary-filter"
          >
            <option value="all">全部状态</option>
            <option value="done">已完成</option>
            <option value="pending">待处理</option>
            <option value="running">进行中</option>
            <option value="failed">失败</option>
          </select>
          <select
            value={selectedModelId || ''}
            onChange={(e) => onModelChange?.(Number(e.target.value) || null)}
            disabled={batchRunning}
            className="enrichment-summary-model"
          >
            {(models || [])
              .filter((m) => (m.capability || 'chat') === 'chat' && m.enabled)
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            {(models || []).filter(
              (m) => (m.capability || 'chat') === 'chat' && !m.enabled
            ).length > 0 && (
              <optgroup label="已禁用">
                {(models || [])
                  .filter(
                    (m) => (m.capability || 'chat') === 'chat' && !m.enabled
                  )
                  .map((m) => (
                    <option key={m.id} value={m.id} disabled>
                      {m.name}
                    </option>
                  ))}
              </optgroup>
            )}
          </select>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onRunBatch?.(['summary'])}
            disabled={batchRunning || !selectedModelId}
          >
            {batchRunning ? (
              <span className="loading-spinner small" />
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <polygon
                  points="5 3 19 12 5 21 5 3"
                  stroke="currentColor"
                  strokeWidth="2"
                />
              </svg>
            )}
            跑总结
          </button>
        </div>
      </header>

      <div className="enrichment-summary-table-wrap">
        <table className="enrichment-summary-table">
          <thead>
            <tr>
              <th style={{ width: 60 }}>#</th>
              <th>标题</th>
              <th style={{ width: 90 }}>状态</th>
              <th style={{ width: 110 }}>场景</th>
              <th>摘要预览</th>
              <th style={{ width: 140 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="enrichment-summary-empty">
                  {items.length === 0
                    ? '该书尚未生成总结, 请先回到「加料」视图批量处理'
                    : '没有匹配的章节'}
                </td>
              </tr>
            ) : (
              filtered.map((it) => (
                <tr
                  key={it.chapter_id}
                  className={openId === it.chapter_id ? 'active' : ''}
                >
                  <td className="enrichment-summary-num">{it.chapter_number}</td>
                  <td className="enrichment-summary-title">{it.title || '—'}</td>
                  <td>
                    <StatusDot status={it.summary_status} label="摘要" />
                    <span className="enrichment-summary-status-text">
                      {STATUS_DOTS[it.summary_status]?.label || '待处理'}
                    </span>
                  </td>
                  <td className="enrichment-summary-scene">
                    {it.scene_tag ? (
                      <span className="enrichment-summary-scene-tag">
                        {it.scene_tag}
                      </span>
                    ) : (
                      <span className="enrichment-summary-muted">—</span>
                    )}
                  </td>
                  <td className="enrichment-summary-preview">
                    {it.summary_status === 'done'
                      ? truncate(it.summary || '', 60)
                      : '—'}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost small"
                      onClick={() =>
                        setOpenId(openId === it.chapter_id ? null : it.chapter_id)
                      }
                    >
                      {openId === it.chapter_id ? '收起' : '查看'}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {openId && (
        <DetailDrawer
          detail={detail}
          loading={detailLoading}
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  );
}

function DetailDrawer({ detail, loading, onClose }) {
  if (!detail) {
    return (
      <div className="enrichment-summary-drawer">
        <div className="enrichment-summary-drawer-head">
          <h4>详情</h4>
          <button type="button" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="library-list-loading">
          <div className="loading-spinner small" />
          <span>载入详情...</span>
        </div>
      </div>
    );
  }
  const rec = detail.recognition || {};
  const characters = Array.isArray(rec.characters) ? rec.characters : [];
  const events = Array.isArray(rec.events) ? rec.events : [];
  return (
    <div className="enrichment-summary-drawer">
      <div className="enrichment-summary-drawer-head">
        <h4>
          第 {detail.chapter_number} 章 {detail.title}
        </h4>
        <button type="button" onClick={onClose}>
          ×
        </button>
      </div>
      {loading ? (
        <div className="library-list-loading">
          <div className="loading-spinner small" />
          <span>载入详情...</span>
        </div>
      ) : (
        <div className="enrichment-summary-drawer-body">
          <section>
            <h5>情节概要</h5>
            <p>{detail.summary || <em>未生成</em>}</p>
          </section>
          <section>
            <h5>登场人物 ({characters.length})</h5>
            {characters.length === 0 ? (
              <p className="enrichment-summary-muted">未识别</p>
            ) : (
              <ul>
                {characters.map((c, i) => (
                  <li key={i}>
                    <strong>{c.name || `人物${i + 1}`}</strong>
                    {c.description && <span> — {c.description}</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <h5>关键事件 ({events.length})</h5>
            {events.length === 0 ? (
              <p className="enrichment-summary-muted">未识别</p>
            ) : (
              <ol>
                {events.map((e, i) => (
                  <li key={i}>
                    <strong>{e.name || `事件${i + 1}`}</strong>
                    {e.description && <span> — {e.description}</span>}
                  </li>
                ))}
              </ol>
            )}
          </section>
          {detail.scene_tag && (
            <section>
              <h5>场景标签</h5>
              <span className="enrichment-summary-scene-tag">
                {detail.scene_tag}
              </span>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
