import { useEffect, useMemo, useRef } from 'react';
import { alignParagraphs, alignParagraphsFromSegments } from '../../utils/paragraphDiff.js';

/**
 * 并排对比视图: 左原文, 右改写, 段落级同步滚动.
 *
 * - 'equal' 段: 同一行, 灰色背景标识"未变"
 * - 'modified': 左右各占一段, 黄色边框标识"已修改"
 * - 'orig_only': 左侧占段, 右侧占位"已删除"
 * - 'rwt_only': 右侧占段, 左侧占位"AI 新增"
 */
export function SideBySideReader({ original = '', rewrite = '', diffSegments = null }) {
  const pairs = useMemo(() => {
    if (Array.isArray(diffSegments) && diffSegments.length > 0) {
      return alignParagraphsFromSegments(diffSegments);
    }
    return alignParagraphs(original, rewrite);
  }, [diffSegments, original, rewrite]);
  const leftRef = useRef(null);
  const rightRef = useRef(null);
  const syncing = useRef(false);

  useEffect(() => {
    const left = leftRef.current;
    const right = rightRef.current;
    if (!left || !right) return undefined;
    const onScrollLeft = () => {
      if (syncing.current) return;
      syncing.current = true;
      right.scrollTop = left.scrollTop;
      requestAnimationFrame(() => { syncing.current = false; });
    };
    const onScrollRight = () => {
      if (syncing.current) return;
      syncing.current = true;
      left.scrollTop = right.scrollTop;
      requestAnimationFrame(() => { syncing.current = false; });
    };
    left.addEventListener('scroll', onScrollLeft, { passive: true });
    right.addEventListener('scroll', onScrollRight, { passive: true });
    return () => {
      left.removeEventListener('scroll', onScrollLeft);
      right.removeEventListener('scroll', onScrollRight);
    };
  }, [pairs]);

  if (pairs.length === 0) {
    return (
      <div className="side-by-side-reader">
        <div className="side-by-side-empty">原文 / 改写均为空</div>
      </div>
    );
  }

  return (
    <div className="side-by-side-reader">
      <div className="side-by-side-cols">
        <div className="side-by-side-col orig" ref={leftRef}>
          <header className="side-by-side-col-head">原文</header>
          <div className="side-by-side-col-body">
            {pairs.map((p, i) => {
              // eslint-disable-next-line react/no-array-index-key
              const key = `l-${i}`;
              if (p.kind === 'equal') {
                return (
                  <div key={key} className="side-by-side-row equal">
                    <span className="side-by-side-tag">未变</span>
                    <p>{p.origText}</p>
                  </div>
                );
              }
              if (p.kind === 'orig_only') {
                return (
                  <div key={key} className="side-by-side-row orig-only">
                    <span className="side-by-side-tag">仅原文</span>
                    <p>{p.origText}</p>
                  </div>
                );
              }
              if (p.kind === 'rwt_only') {
                return (
                  <div key={key} className="side-by-side-row empty">
                    <span className="side-by-side-tag">—</span>
                    <p className="muted">（改写新增, 左侧无对应段落）</p>
                  </div>
                );
              }
              // modified
              return (
                <div key={key} className="side-by-side-row modified">
                  <span className="side-by-side-tag">修改</span>
                  <p>{p.origText}</p>
                </div>
              );
            })}
          </div>
        </div>
        <div className="side-by-side-col rwt" ref={rightRef}>
          <header className="side-by-side-col-head">改写 (AI 加料)</header>
          <div className="side-by-side-col-body">
            {pairs.map((p, i) => {
              // eslint-disable-next-line react/no-array-index-key
              const key = `r-${i}`;
              if (p.kind === 'equal') {
                return (
                  <div key={key} className="side-by-side-row equal">
                    <span className="side-by-side-tag">未变</span>
                    <p>{p.rwtText}</p>
                  </div>
                );
              }
              if (p.kind === 'rwt_only') {
                return (
                  <div key={key} className="side-by-side-row rwt-only">
                    <span className="side-by-side-tag">AI 新增</span>
                    <p>{p.rwtText}</p>
                  </div>
                );
              }
              if (p.kind === 'orig_only') {
                return (
                  <div key={key} className="side-by-side-row empty">
                    <span className="side-by-side-tag">—</span>
                    <p className="muted">（原文独有, 改写已删除）</p>
                  </div>
                );
              }
              return (
                <div key={key} className="side-by-side-row modified">
                  <span className="side-by-side-tag">修改</span>
                  <p>{p.rwtText}</p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
