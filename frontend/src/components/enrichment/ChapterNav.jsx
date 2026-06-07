import { useEffect, useMemo, useState } from 'react';

const STATUS_DOTS = {
  pending: { label: '待处理', cls: 'dot-pending' },
  running: { label: '进行中', cls: 'dot-running' },
  done: { label: '已完成', cls: 'dot-done' },
  failed: { label: '失败', cls: 'dot-failed' },
  skipped: { label: '跳过', cls: 'dot-skipped' },
};

function statusToDotKey(s) {
  return STATUS_DOTS[s] ? s : 'pending';
}

function StatusDots({ summary, recognition, rewrite }) {
  return (
    <span className="chapter-status-dots" title="总结/识别/改写">
      <span className={`chapter-dot ${STATUS_DOTS[statusToDotKey(summary)].cls}`} title={`摘要: ${STATUS_DOTS[statusToDotKey(summary)].label}`} />
      <span className={`chapter-dot ${STATUS_DOTS[statusToDotKey(recognition)].cls}`} title={`识别: ${STATUS_DOTS[statusToDotKey(recognition)].label}`} />
      <span className={`chapter-dot ${STATUS_DOTS[statusToDotKey(rewrite)].cls}`} title={`改写: ${STATUS_DOTS[statusToDotKey(rewrite)].label}`} />
    </span>
  );
}

function ChapterRow({ item, active, onSelect }) {
  return (
    <button
      type="button"
      className={`enrichment-chapter-row ${active ? 'active' : ''}`}
      onClick={() => onSelect(item.chapter_id)}
    >
      <div className="enrichment-chapter-row-head">
        <span className="enrichment-chapter-row-title">
          第 {item.chapter_number} 章 {item.title}
        </span>
        <StatusDots
          summary={item.summary_status}
          recognition={item.recognition_status}
          rewrite={item.rewrite_status}
        />
      </div>
      {item.scene_tag && (
        <span className="enrichment-chapter-row-tag">{item.scene_tag}</span>
      )}
    </button>
  );
}

export function ChapterNav({
  items = [],
  selectedId,
  onSelect,
  loading,
  onJumpTop,
  onJumpBottom,
}) {
  const [query, setQuery] = useState('');

  useEffect(() => {
    setQuery('');
  }, [items]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) =>
        String(it.chapter_number).includes(q) ||
        (it.title || '').toLowerCase().includes(q)
    );
  }, [items, query]);

  return (
    <div className="enrichment-chapter-nav">
      <div className="enrichment-chapter-nav-tools">
        <label className="project-search-bar">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
            <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" />
          </svg>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索章节号 / 标题"
          />
        </label>
        <div className="enrichment-chapter-nav-jump">
          <button type="button" onClick={onJumpTop} title="回到顶部">↑</button>
          <button type="button" onClick={onJumpBottom} title="回到底部">↓</button>
        </div>
      </div>
      <div className="enrichment-chapter-nav-list">
        {loading ? (
          <div className="library-list-loading">
            <div className="loading-spinner small"></div>
            <span>载入中…</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="library-list-empty">
            {items.length === 0 ? '该书尚未解析章节' : '没有匹配的章节'}
          </div>
        ) : (
          filtered.map((it) => (
            <ChapterRow
              key={it.chapter_id}
              item={it}
              active={it.chapter_id === selectedId}
              onSelect={onSelect}
            />
          ))
        )}
      </div>
    </div>
  );
}