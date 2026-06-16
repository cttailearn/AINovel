import { useMemo } from 'react';
import { alignParagraphs, alignParagraphsFromSegments } from '../../utils/paragraphDiff.js';

/**
 * 合并阅读视图: 原文段 / 改写段 交替呈现, 配对的段叠在一起展示.
 *
 * - 段落级别 diff
 * - 'equal' 段: 折叠显示, 单色
 * - 'modified' 段: 上"原文"下"改写"两块 (改写 + 背景色)
 * - 'orig_only' 段: 只显示原文 (灰色)
 * - 'rwt_only' 段: 只显示改写 (绿色高亮, 表示"AI 新增")
 */
export function MergedReader({ original = '', rewrite = '', diffSegments = null }) {
  const pairs = useMemo(() => {
    if (Array.isArray(diffSegments) && diffSegments.length > 0) {
      return alignParagraphsFromSegments(diffSegments);
    }
    return alignParagraphs(original, rewrite);
  }, [diffSegments, original, rewrite]);

  if (pairs.length === 0) {
    return (
      <div className="merged-reader">
        <div className="merged-reader-empty">原文 / 改写均为空</div>
      </div>
    );
  }

  return (
    <div className="merged-reader">
      {pairs.map((p, i) => {
        // eslint-disable-next-line react/no-array-index-key
        if (p.kind === 'equal') {
          return (
            <div key={i} className="merged-paragraph equal">
              <span className="merged-paragraph-tag">未变</span>
              <p className="merged-paragraph-text">{p.origText}</p>
            </div>
          );
        }
        if (p.kind === 'orig_only') {
          return (
            <div key={i} className="merged-paragraph orig-only">
              <span className="merged-paragraph-tag">原文独有</span>
              <p className="merged-paragraph-text">{p.origText}</p>
            </div>
          );
        }
        if (p.kind === 'rwt_only') {
          return (
            <div key={i} className="merged-paragraph rwt-only">
              <span className="merged-paragraph-tag">AI 新增</span>
              <p className="merged-paragraph-text">{p.rwtText}</p>
            </div>
          );
        }
        // modified
        return (
          <div key={i} className="merged-paragraph modified">
            <div className="merged-paragraph-half orig">
              <span className="merged-paragraph-tag">原文</span>
              <p className="merged-paragraph-text">{p.origText}</p>
            </div>
            <div className="merged-paragraph-half rwt">
              <span className="merged-paragraph-tag">改写</span>
              <p className="merged-paragraph-text">{p.rwtText}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
