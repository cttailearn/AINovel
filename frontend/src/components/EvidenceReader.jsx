import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';

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
 * 把单条 evidence 在原文里标出来.
 *
 * 策略: 用 quote 字符串在 chunk.content 里 find; 找不到再退化到 chunk_id 匹配.
 * 若全部失败, 仍展示该 chunk, 把 quote 渲染到顶部作为"提示".
 */
function findHit(quote, content) {
  if (!quote || !content) return null;
  const idx = content.indexOf(quote);
  if (idx >= 0) {
    return { start: idx, end: idx + quote.length };
  }
  // 退化 1: 去掉末尾标点再找
  const trimmed = quote.replace(/[。.!?！？,，;；:："'""'']+$/u, '');
  if (trimmed && trimmed !== quote) {
    const i2 = content.indexOf(trimmed);
    if (i2 >= 0) return { start: i2, end: i2 + trimmed.length };
  }
  // 退化 2: 头部 80% 找
  if (quote.length > 8) {
    const head = quote.slice(0, Math.max(8, Math.floor(quote.length * 0.8)));
    const i3 = content.indexOf(head);
    if (i3 >= 0) return { start: i3, end: i3 + head.length };
  }
  return null;
}

function splitByChunkId(chunks, targetId) {
  if (!targetId) return null;
  // 后端 chunk_id 格式: "chapter_3" / "chunk_005"
  if (targetId.startsWith('chapter_')) {
    const n = parseInt(targetId.slice('chapter_'.length), 10);
    if (Number.isFinite(n)) {
      return chunks.find((c) => c.chunk_number === n) || null;
    }
  }
  if (targetId.startsWith('chunk_')) {
    const n = parseInt(targetId.slice('chunk_'.length), 10);
    if (Number.isFinite(n)) {
      return chunks.find((c) => c.chunk_number === n) || null;
    }
  }
  return null;
}

function HighlightedChunk({ chunk, hit }) {
  const ref = useRef(null);
  useEffect(() => {
    if (hit && ref.current) {
      ref.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [hit, chunk.chunk_number]);

  if (!hit) {
    return (
      <article className="evr-chunk">
        <header className="evr-chunk-head">
          <span className="evr-chunk-num">#{chunk.chunk_number}</span>
          <h4>{chunk.title || `片段 ${chunk.chunk_number}`}</h4>
        </header>
        <p className="evr-chunk-body">{chunk.content}</p>
        <p className="evr-chunk-empty-hint">（未在该片段内找到对应原文, 可能是不同切分粒度导致）</p>
      </article>
    );
  }

  const before = chunk.content.slice(0, hit.start);
  const middle = chunk.content.slice(hit.start, hit.end);
  const after = chunk.content.slice(hit.end);

  return (
    <article className="evr-chunk">
      <header className="evr-chunk-head">
        <span className="evr-chunk-num">#{chunk.chunk_number}</span>
        <h4>{chunk.title || `片段 ${chunk.chunk_number}`}</h4>
        <span className="evr-chunk-meta">{chunk.content.length} 字</span>
      </header>
      <p className="evr-chunk-body" ref={ref}>
        {before}
        <mark className="evr-mark">
          <span className="evr-mark-glyph" aria-hidden>“</span>
          {middle}
          <span className="evr-mark-glyph" aria-hidden>”</span>
        </mark>
        {after}
      </p>
    </article>
  );
}

export function EvidenceReader({
  open,
  onClose,
  novelId,
  novelTitle,
  evidenceList,
  // 单条 evidence 触发的"直接定位"模式: 直接跳到对应 chunk + 高亮
  jumpTo,
  onJumpConsumed,
  chunkSize = 120000,
}) {
  const toast = useToast();
  const [chunks, setChunks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeIdx, setActiveIdx] = useState(0);

  const list = useMemo(() => {
    if (!evidenceList) return [];
    if (Array.isArray(evidenceList)) return evidenceList;
    return [evidenceList];
  }, [evidenceList]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !novelId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.novels.raw(novelId, chunkSize);
        if (cancelled) return;
        setChunks(data?.chunks || []);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : '加载原文失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, novelId, chunkSize]);

  // 处理 "jumpTo" 直接定位请求
  useEffect(() => {
    if (!open || !jumpTo || !chunks.length) return;
    const idx = list.findIndex(
      (e) =>
        e.quote === jumpTo.quote &&
        (e.chunk_id || '') === (jumpTo.chunk_id || '')
    );
    if (idx >= 0) {
      setActiveIdx(idx);
    }
    onJumpConsumed?.();
  }, [open, jumpTo, chunks, list, onJumpConsumed]);

  const activeEvidence = list[activeIdx] || list[0] || null;
  const activeChunk = useMemo(() => {
    if (!activeEvidence) return null;
    return splitByChunkId(chunks, activeEvidence.chunk_id);
  }, [activeEvidence, chunks]);

  const activeHit = useMemo(() => {
    if (!activeEvidence || !activeChunk) return null;
    return findHit(activeEvidence.quote, activeChunk.content);
  }, [activeEvidence, activeChunk]);

  const handleBackdrop = useCallback(
    (e) => {
      if (e.target === e.currentTarget) onClose?.();
    },
    [onClose]
  );

  if (!open) return null;

  return (
    <div className="evr-backdrop" onClick={handleBackdrop}>
      <div
        className="evr-shell"
        role="dialog"
        aria-modal="true"
        aria-label="原文定位"
      >
        <header className="evr-head">
          <div className="evr-head-left">
            <span className="evr-eyebrow">原文定位</span>
            <h2 className="evr-title">{novelTitle || '原文'}</h2>
            <div className="evr-head-meta">
              <span>{chunks.length} 个片段</span>
              {activeEvidence && (
                <>
                  <span className="evr-head-dot">·</span>
                  <span>
                    第 {activeIdx + 1} / {list.length} 条证据
                  </span>
                </>
              )}
            </div>
          </div>
          <button
            type="button"
            className="evr-close"
            onClick={onClose}
            aria-label="关闭"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path
                d="M18 6L6 18M6 6l12 12"
                stroke="currentColor"
                strokeWidth="2"
              />
            </svg>
          </button>
        </header>

        <div className="evr-body">
          {/* 左侧: 证据列表 (footnote-style) */}
          {list.length > 1 && (
            <aside className="evr-side">
              <h3 className="evr-side-title">证据清单</h3>
              <ol className="evr-list">
                {list.map((ev, i) => (
                  <li
                    key={i}
                    className={`evr-list-item ${
                      i === activeIdx ? 'is-active' : ''
                    }`}
                  >
                    <button
                      type="button"
                      className="evr-list-btn"
                      onClick={() => setActiveIdx(i)}
                    >
                      <span className="evr-list-num">{String(i + 1).padStart(2, '0')}</span>
                      <span className="evr-list-quote">
                        {ev.quote ? `“${ev.quote.slice(0, 28)}${ev.quote.length > 28 ? '…' : ''}”` : '(无原文)'}
                      </span>
                      <span className={`evr-list-strategy ${STRATEGY_TONE[ev.strategy] || ''}`}>
                        {STRATEGY_LABEL[ev.strategy] || ev.strategy}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            </aside>
          )}

          {/* 右侧: 证据 + 原文 */}
          <main className="evr-main">
            {activeEvidence && (
              <section className="evr-quote-card">
                <div className="evr-quote-head">
                  <span className="evr-quote-label">引文</span>
                  <span className={`evr-quote-strategy ${STRATEGY_TONE[activeEvidence.strategy] || ''}`}>
                    {STRATEGY_LABEL[activeEvidence.strategy] || activeEvidence.strategy}
                  </span>
                  {activeEvidence.chunk_id && (
                    <span className="evr-quote-chunk">片段 {activeEvidence.chunk_id}</span>
                  )}
                  {typeof activeEvidence.confidence === 'number' && (
                    <span className="evr-quote-confidence">
                      置信度 {Math.round(activeEvidence.confidence * 100)}%
                    </span>
                  )}
                </div>
                <blockquote className="evr-quote">
                  {activeEvidence.quote || '(该实体未提供 evidence 文本)'}
                </blockquote>
                {list.length > 1 && (
                  <div className="evr-quote-nav">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setActiveIdx((i) => Math.max(0, i - 1))
                      }
                      disabled={activeIdx === 0}
                    >
                      上一条
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setActiveIdx((i) => Math.min(list.length - 1, i + 1))
                      }
                      disabled={activeIdx >= list.length - 1}
                    >
                      下一条
                    </button>
                  </div>
                )}
              </section>
            )}

            {loading ? (
              <div className="evr-loading">
                <div className="loading-spinner large"></div>
                <p>正在加载原文…</p>
              </div>
            ) : error ? (
              <div className="evr-error">
                <p>加载失败：{error}</p>
                <span>请检查小说文件是否仍可访问</span>
              </div>
            ) : !activeChunk ? (
              <div className="evr-empty">
                <p>未找到对应原文片段</p>
                <span>
                  该证据的 <code>{activeEvidence?.chunk_id || '(空)'}</code> 不在已切分的片段中
                </span>
              </div>
            ) : (
              <HighlightedChunk
                key={`${activeChunk.chunk_number}-${activeIdx}`}
                chunk={activeChunk}
                hit={activeHit}
              />
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
