import { useEffect, useMemo, useRef } from 'react';

/**
 * 渲染带 diff 高亮的阅读器正文.
 * segments: [{type: 'unchanged' | 'added' | 'removed', text: string}]
 * truncated: boolean - 服务端是否因长度超限退化
 */
export function HighlightedReader({ segments, truncated, scrollRef, onFirstHighlightScroll }) {
  const firstHighlightRef = useRef(null);
  const scrolledRef = useRef(false);

  // 默认滚动到第一个高亮位置
  useEffect(() => {
    if (scrolledRef.current) return;
    if (!firstHighlightRef.current || !scrollRef?.current) return;
    const el = firstHighlightRef.current;
    const container = scrollRef.current;
    const elRect = el.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const offset =
      elRect.top - containerRect.top + container.scrollTop -
      container.clientHeight * 0.3;
    container.scrollTo({ top: Math.max(0, offset), behavior: 'smooth' });
    scrolledRef.current = true;
    onFirstHighlightScroll?.();
  }, [segments, scrollRef, onFirstHighlightScroll]);

  const counts = useMemo(() => {
    let added = 0;
    let removed = 0;
    let unchanged = 0;
    (segments || []).forEach((s) => {
      if (s.type === 'added') added += s.text.length;
      else if (s.type === 'removed') removed += s.text.length;
      else unchanged += s.text.length;
    });
    return { added, removed, unchanged };
  }, [segments]);

  return (
    <div className="highlighted-reader">
      {truncated && (
        <div className="highlighted-reader-warn">
          ⚠ 文本过长, 已截断对比; 完整数据请到「应用历史」中查看。
        </div>
      )}
      <div className="highlighted-reader-legend">
        <span>
          <i className="legend-swatch swatch-added" /> 新增
          <strong>+{counts.added.toLocaleString()}</strong>
        </span>
        <span>
          <i className="legend-swatch swatch-removed" /> 改写 / 删除
          <strong>-{counts.removed.toLocaleString()}</strong>
        </span>
        <span>
          <i className="legend-swatch swatch-unchanged" /> 未变
          <strong>{counts.unchanged.toLocaleString()}</strong>
        </span>
      </div>
      <pre className="highlighted-reader-text">
        {(segments || []).map((seg, i) => {
          if (seg.type === 'added') {
            return (
              <ins
                key={i}
                className="diff-added"
                ref={i === 0 && seg.type !== 'unchanged' ? firstHighlightRef : null}
              >
                {seg.text}
              </ins>
            );
          }
          if (seg.type === 'removed') {
            return (
              <del
                key={i}
                className="diff-removed"
                ref={i === 0 ? firstHighlightRef : null}
              >
                {seg.text}
              </del>
            );
          }
          // unchanged
          return <span key={i}>{seg.text}</span>;
        })}
      </pre>
    </div>
  );
}
