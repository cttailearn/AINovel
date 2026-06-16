/**
 * 段落切分 + 段落级 diff 配对.
 *
 * 设计目标:
 * - 把 original / rewrite 切成段落数组
 * - 对段落做 LCS 配对, 生成 [{kind, origIdx, rwtIdx, origText, rwtText}, ...]
 *   kind: 'equal' | 'modified' | 'orig_only' | 'rwt_only'
 * - 上层 MergedReader / SideBySideReader 拿到配对数组后, 一行行渲染
 */
import { splitUnits, lcsAlign } from './textDiffUtil.js';

/** 把文本按段落切. 段落分隔: 双换行 / 单换行. 中文段落也会被保留. */
export function splitParagraphs(text) {
  if (!text) return [];
  // 优先按双换行, 再按单换行, 再按句号兜底
  return text
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
    .flatMap((p) => {
      // 太长的"段"再按单换行切
      if (p.length > 600) {
        return p.split(/\n+/).map((s) => s.trim()).filter(Boolean);
      }
      return [p];
    });
}

/**
 * 段落级 LCS 配对.
 * @returns {Array<{kind, origIdx, rwtIdx, origText, rwtText}>}
 *  - kind='equal': origText===rwtText, 两个 idx 都存在
 *  - kind='modified': 两段都存在, 但文本不同
 *  - kind='orig_only': 原文独有
 *  - kind='rwt_only': 改写独有
 */
export function alignParagraphs(original, rewrite) {
  const a = splitParagraphs(original);
  const b = splitParagraphs(rewrite);
  if (a.length === 0 && b.length === 0) return [];
  if (a.length === 0) {
    return b.map((t, i) => ({ kind: 'rwt_only', origIdx: -1, rwtIdx: i, origText: '', rwtText: t }));
  }
  if (b.length === 0) {
    return a.map((t, i) => ({ kind: 'orig_only', origIdx: i, rwtIdx: -1, origText: t, rwtText: '' }));
  }

  // 用每段前 24 字符 (归一化) 作为 LCS 单位, 加速 + 减少内存
  const keyOf = (s) => s.replace(/\s+/g, '').slice(0, 24);
  const aKey = a.map(keyOf);
  const bKey = b.map(keyOf);

  // 1) 用 key LCS 找配对锚点
  const keyPairs = lcsAlign(aKey, bKey);
  // 2) 对未配对的"长段", 进一步按句级 LCS 切
  const result = [];
  let ai = 0;
  let bi = 0;
  for (const [pa, pb] of keyPairs) {
    // 处理 ai 之前的 orig_only
    while (ai < pa) {
      result.push({
        kind: 'orig_only',
        origIdx: ai,
        rwtIdx: -1,
        origText: a[ai],
        rwtText: '',
      });
      ai++;
    }
    while (bi < pb) {
      result.push({
        kind: 'rwt_only',
        origIdx: -1,
        rwtIdx: bi,
        origText: '',
        rwtText: b[bi],
      });
      bi++;
    }
    // 处理配对锚点
    const oText = a[pa];
    const rText = b[pb];
    if (oText === rText) {
      result.push({ kind: 'equal', origIdx: pa, rwtIdx: pb, origText: oText, rwtText: rText });
    } else {
      result.push({ kind: 'modified', origIdx: pa, rwtIdx: pb, origText: oText, rwtText: rText });
    }
    ai = pa + 1;
    bi = pb + 1;
  }
  // 收尾
  while (ai < a.length) {
    result.push({ kind: 'orig_only', origIdx: ai, rwtIdx: -1, origText: a[ai], rwtText: '' });
    ai++;
  }
  while (bi < b.length) {
    result.push({ kind: 'rwt_only', origIdx: -1, rwtIdx: bi, origText: '', rwtText: b[bi] });
    bi++;
  }
  return result;
}

function splitSegmentParagraphs(text) {
  return splitParagraphs(text || '');
}

function buildPairsFromChangeRun(removedItems, addedItems) {
  const result = [];
  const size = Math.max(removedItems.length, addedItems.length);
  for (let i = 0; i < size; i += 1) {
    const origText = removedItems[i] || '';
    const rwtText = addedItems[i] || '';
    if (origText && rwtText) {
      result.push({
        kind: origText === rwtText ? 'equal' : 'modified',
        origIdx: -1,
        rwtIdx: -1,
        origText,
        rwtText,
      });
    } else if (origText) {
      result.push({
        kind: 'orig_only',
        origIdx: -1,
        rwtIdx: -1,
        origText,
        rwtText: '',
      });
    } else if (rwtText) {
      result.push({
        kind: 'rwt_only',
        origIdx: -1,
        rwtIdx: -1,
        origText: '',
        rwtText,
      });
    }
  }
  return result;
}

export function alignParagraphsFromSegments(segments = []) {
  const result = [];
  let removedBuffer = [];
  let addedBuffer = [];

  const flushBuffers = () => {
    if (removedBuffer.length === 0 && addedBuffer.length === 0) return;
    result.push(...buildPairsFromChangeRun(removedBuffer, addedBuffer));
    removedBuffer = [];
    addedBuffer = [];
  };

  (segments || []).forEach((segment) => {
    if (!segment?.text) return;
    if (segment.type === 'unchanged') {
      flushBuffers();
      splitSegmentParagraphs(segment.text).forEach((text) => {
        result.push({
          kind: 'equal',
          origIdx: -1,
          rwtIdx: -1,
          origText: text,
          rwtText: text,
        });
      });
      return;
    }
    if (segment.type === 'removed') {
      removedBuffer.push(...splitSegmentParagraphs(segment.text));
      return;
    }
    if (segment.type === 'added') {
      addedBuffer.push(...splitSegmentParagraphs(segment.text));
    }
  });

  flushBuffers();
  return result;
}

// ============== 内部工具 (从 textDiffUtil 复用) ==============

// 重新导出, 避免外部依赖复杂
export { splitUnits, lcsAlign };
