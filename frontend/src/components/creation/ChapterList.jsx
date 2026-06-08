// 章节列表 + 单章节操作 (打开/选择/编辑/确认)
import { useState } from 'react';

const STATUS_META = {
  draft: { label: '草稿', tone: 'muted' },
  generating: { label: '生成中', tone: 'active' },
  generated: { label: '已生成', tone: 'active' },
  selected: { label: '已选待编辑', tone: 'warn' },
  edited: { label: '已编辑', tone: 'warn' },
  confirmed: { label: '已确认', tone: 'ok' },
};

function StatusPill({ status }) {
  const m = STATUS_META[status] || { label: status, tone: 'muted' };
  return <span className={`status-pill tone-${m.tone}`}>{m.label}</span>;
}

export function ChapterList({
  chapters,
  selectedChapterId,
  onSelect,
  loading = false,
  generating = false,
}) {
  if (loading) {
    return (
      <div className="creation-chapter-list muted small">
        加载章节...
      </div>
    );
  }
  if (!chapters || chapters.length === 0) {
    return (
      <div className="creation-chapter-list empty muted small">
        暂无章节. 点击右上角「生成下一章」开始创作.
      </div>
    );
  }
  return (
    <div className="creation-chapter-list">
      {chapters.map((ch) => {
        const isActive = selectedChapterId === ch.id;
        return (
          <button
            key={ch.id}
            type="button"
            className={`creation-chapter-item ${isActive ? 'active' : ''}`}
            onClick={() => onSelect(ch.id)}
            disabled={generating && !isActive}
            title={ch.title || `第 ${ch.chapter_no} 章`}
          >
            <div className="creation-chapter-item-head">
              <span className="creation-chapter-no">第 {ch.chapter_no} 章</span>
              <StatusPill status={ch.status} />
            </div>
            <div className="creation-chapter-item-title">
              {ch.title || '(未命名)'}
            </div>
            <div className="creation-chapter-item-meta">
              {ch.word_count ? `${ch.word_count} 字` : '—'}
              {ch.variants?.length ? ` · ${ch.variants.length} 候选` : ''}
              {ch.kg_extracted ? ' · 已入图谱' : ''}
            </div>
          </button>
        );
      })}
    </div>
  );
}
