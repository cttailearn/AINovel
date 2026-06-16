// 章节列表 + 单章节操作 (打开/选择/编辑/确认)
import { useCallback, useState } from 'react';
import { FixedSizeList as VirtualList } from 'react-window';

const STATUS_META = {
  draft: { label: '草稿', tone: 'muted' },
  generating: { label: '生成中', tone: 'active' },
  generated: { label: '已生成', tone: 'active' },
  selected: { label: '已选待编辑', tone: 'warn' },
  edited: { label: '已编辑', tone: 'warn' },
  confirmed: { label: '已确认', tone: 'ok' },
};

// 修复 #16: 把 kg_extracted_at 时间戳格式化成"X 分钟前"等人类可读形式
function formatRelativeTime(iso) {
  if (!iso) return null;
  try {
    const t = new Date(typeof iso === 'string' && !iso.includes('T') ? iso.replace(' ', 'T') : iso);
    if (Number.isNaN(t.getTime())) return null;
    const diffMs = Date.now() - t.getTime();
    if (diffMs < 60_000) return '刚刚';
    if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)} 分钟前`;
    if (diffMs < 86_400_000) return `${Math.floor(diffMs / 3_600_000)} 小时前`;
    return `${Math.floor(diffMs / 86_400_000)} 天前`;
  } catch {
    return null;
  }
}

function StatusPill({ status }) {
  const m = STATUS_META[status] || { label: status, tone: 'muted' };
  return <span className={`status-pill tone-${m.tone}`}>{m.label}</span>;
}

function ChapterRow({ chapter, isActive, generating, onSelect }) {
  const kgRelative = formatRelativeTime(chapter.kg_extracted_at);
  return (
    <button
      type="button"
      className={`creation-chapter-item ${isActive ? 'active' : ''}`}
      onClick={() => onSelect(chapter.id)}
      disabled={generating && !isActive}
      title={chapter.title || `第 ${chapter.chapter_no} 章`}
    >
      <div className="creation-chapter-item-head">
        <span className="creation-chapter-no">第 {chapter.chapter_no} 章</span>
        <StatusPill status={chapter.status} />
      </div>
      <div className="creation-chapter-item-title">
        {chapter.title || '(未命名)'}
      </div>
      <div className="creation-chapter-item-meta">
        {chapter.word_count ? `${chapter.word_count} 字` : '—'}
        {chapter.variants?.length ? ` · ${chapter.variants.length} 候选` : ''}
        {chapter.kg_extracted ? (
          kgRelative ? ` · 已入图谱 (${kgRelative})` : ' · 已入图谱'
        ) : ''}
      </div>
    </button>
  );
}

function ChapterRowVirtual({ index, style, data }) {
  const { chapters, selectedChapterId, generating, onSelect } = data;
  const ch = chapters[index];
  if (!ch) return null;
  return (
    <div style={style} className="creation-chapter-virtual-row">
      <ChapterRow
        chapter={ch}
        isActive={selectedChapterId === ch.id}
        generating={generating}
        onSelect={onSelect}
      />
    </div>
  );
}

// 修复 #24: 超过该阈值启用虚拟滚动, 避免 100+ 章节时整列表全量渲染.
const VIRTUAL_THRESHOLD = 30;
const VIRTUAL_ITEM_HEIGHT = 88;
const VIRTUAL_MAX_VIEWPORT = 480;

export function ChapterList({
  chapters,
  selectedChapterId,
  onSelect,
  loading = false,
  generating = false,
}) {
  const [viewportHeight] = useState(
    typeof window === 'undefined' ? VIRTUAL_MAX_VIEWPORT : Math.min(window.innerHeight - 200, VIRTUAL_MAX_VIEWPORT)
  );

  const handleSelect = useCallback(
    (id) => {
      onSelect?.(id);
    },
    [onSelect]
  );

  if (loading) {
    return (
      <div className="creation-chapter-list muted small">加载章节...</div>
    );
  }
  if (!chapters || chapters.length === 0) {
    return (
      <div className="creation-chapter-list empty muted small">
        暂无章节. 点击右上角「生成下一章」开始创作.
      </div>
    );
  }

  // 章节数较少, 走原始全量渲染 (避免虚拟化带来的 padding / scrollTop 复杂度).
  if (chapters.length < VIRTUAL_THRESHOLD) {
    return (
      <div className="creation-chapter-list">
        {chapters.map((ch) => (
          <ChapterRow
            key={ch.id}
            chapter={ch}
            isActive={selectedChapterId === ch.id}
            generating={generating}
            onSelect={handleSelect}
          />
        ))}
      </div>
    );
  }

  // 章节数较多, 启用虚拟滚动.
  const itemData = {
    chapters,
    selectedChapterId,
    generating,
    onSelect: handleSelect,
  };
  return (
    <div className="creation-chapter-list virtualized">
      <VirtualList
        height={viewportHeight}
        itemCount={chapters.length}
        itemSize={VIRTUAL_ITEM_HEIGHT}
        width="100%"
        itemData={itemData}
        overscanCount={4}
      >
        {ChapterRowVirtual}
      </VirtualList>
    </div>
  );
}
