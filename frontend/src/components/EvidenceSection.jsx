import { useState } from 'react';

const STRATEGY_LABEL = {
  anchor: '锚点定位',
  head: '段首兜底',
  fallback: '未找到',
};

const STRATEGY_TONE = {
  anchor: 'tone-strong',
  head: 'tone-soft',
  fallback: 'tone-mute',
};

/**
 * 单条 evidence 卡片: 左编号 + 引文 + 锚点元信息 + 操作.
 */
function EvidenceItem({ evidence, index, onJump }) {
  const [expanded, setExpanded] = useState(false);
  const hasOffset =
    typeof evidence.start === 'number' && typeof evidence.end === 'number';
  const longQuote = (evidence.quote || '').length > 100;

  return (
    <li className="kg-evi-item">
      <span className="kg-evi-num">{String(index + 1).padStart(2, '0')}</span>
      <div className="kg-evi-body">
        <p
          className={`kg-evi-quote ${expanded ? 'is-expanded' : ''}`}
          onClick={() => longQuote && setExpanded((v) => !v)}
        >
          <span className="kg-evi-glyph" aria-hidden>“</span>
          {evidence.quote || '(该实体未提供 evidence 文本)'}
          <span className="kg-evi-glyph" aria-hidden>”</span>
          {longQuote && (
            <button
              type="button"
              className="kg-evi-expand"
              onClick={(e) => {
                e.stopPropagation();
                setExpanded((v) => !v);
              }}
            >
              {expanded ? '收起' : '展开'}
            </button>
          )}
        </p>
        <div className="kg-evi-meta">
          {evidence.chunk_id && (
            <span className="kg-evi-meta-pill">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" strokeWidth="2">
                <path d="M4 6h16M4 12h16M4 18h10" stroke="currentColor" strokeLinecap="round" />
              </svg>
              {evidence.chunk_id}
            </span>
          )}
          {hasOffset && (
            <span className="kg-evi-meta-pill" title="字符 offset">
              偏移 {evidence.start}–{evidence.end}
            </span>
          )}
          {typeof evidence.sentence_idx === 'number' && (
            <span className="kg-evi-meta-pill">第 {evidence.sentence_idx + 1} 句</span>
          )}
          {evidence.strategy && (
            <span className={`kg-evi-meta-pill kg-evi-strategy ${STRATEGY_TONE[evidence.strategy] || ''}`}>
              {STRATEGY_LABEL[evidence.strategy] || evidence.strategy}
            </span>
          )}
        </div>
      </div>
      {onJump && (
        <button
          type="button"
          className="kg-evi-jump"
          onClick={() => onJump(evidence)}
          title="在原文中定位"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" strokeWidth="2">
            <path d="M7 17L17 7M9 7h8v8" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          定位
        </button>
      )}
    </li>
  );
}

/**
 * EntityDetailModal 内部用: 展示 evidence 列表 + 置信度总览.
 * ``extras`` 是从后端 entity.extras 透传过来的 dict.
 */
export function EvidenceSection({ extras, onJump }) {
  const list = Array.isArray(extras?.evidence) ? extras.evidence : [];
  const confidence = typeof extras?.confidence === 'number' ? extras.confidence : null;

  if (list.length === 0 && confidence == null) {
    return (
      <section className="kg-detail-section">
        <h4 className="kg-detail-section-title">原文出处</h4>
        <p className="kg-evi-empty">该实体未携带 evidence 引用（可能为旧数据）。</p>
      </section>
    );
  }

  return (
    <section className="kg-detail-section">
      <h4 className="kg-detail-section-title">
        原文出处
        {list.length > 0 && (
          <span className="kg-detail-section-count">{list.length}</span>
        )}
        {confidence != null && (
          <span className="kg-evi-confidence">
            置信度 {Math.round(confidence * 100)}%
            <span
              className="kg-evi-confidence-bar"
              aria-hidden
              style={{ '--ratio': confidence }}
            />
          </span>
        )}
      </h4>
      {list.length > 0 ? (
        <ul className="kg-evi-list">
          {list.map((ev, i) => (
            <EvidenceItem key={i} evidence={ev} index={i} onJump={onJump} />
          ))}
        </ul>
      ) : (
        <p className="kg-evi-empty">无 evidence 列表</p>
      )}
    </section>
  );
}
