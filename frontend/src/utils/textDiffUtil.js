/**
 * 通用 LCS / diff 工具 (前端实现, 避免后端往返).
 * 性能: O(M*N) DP, 适合百级以内的句子级 / 段落级 LCS.
 */

const SENT_SPLIT = /(?<=[。!?！？\n])/;

export function splitUnits(text) {
  if (!text) return [];
  const pieces = [];
  for (const raw of SENT_SPLIT.split(text)) {
    const s = raw.trim();
    if (!s) continue;
    if (s.length <= 120) {
      pieces.push(s);
    } else {
      const step = 80;
      for (let i = 0; i < s.length; i += step) {
        pieces.push(s.slice(i, i + step));
      }
    }
  }
  return pieces;
}

/**
 * LCS DP 表 + 回溯, 返回 [(idxA, idxB), ...] 的配对序列 (按 a 顺序).
 */
export function lcsAlign(a, b) {
  const m = a.length;
  const n = b.length;
  if (m === 0 || n === 0) {
    if (m === 0) return [];
    if (n === 0) return [];
  }
  const table = Array.from({ length: m + 1 }, () => new Uint32Array(n + 1));
  for (let i = 0; i < m; i++) {
    const ai = a[i];
    for (let j = 0; j < n; j++) {
      if (ai === b[j]) {
        table[i + 1][j + 1] = table[i][j] + 1;
      } else {
        const up = table[i][j + 1];
        const left = table[i + 1][j];
        table[i + 1][j + 1] = up >= left ? up : left;
      }
    }
  }
  // 回溯
  const pairs = [];
  let i = m;
  let j = n;
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1]) {
      pairs.push([i - 1, j - 1]);
      i--;
      j--;
    } else if (table[i - 1][j] >= table[i][j - 1]) {
      i--;
    } else {
      j--;
    }
  }
  pairs.reverse();
  return pairs;
}

/**
 * 把 LCS 配对展开为"对账式" 段序列 (==, del, add, mod).
 * 输入: a / b 是字符串数组, pairs 是 LCS 配对.
 * 输出: [{type: 'equal'|'removed'|'added'|'modified', text?, aText?, bText?}]
 */
export function coalesceDiff(a, b, pairs) {
  const out = [];
  let i = 0;
  let j = 0;
  for (const [pa, pb] of pairs) {
    while (i < pa) {
      out.push({ type: 'removed', text: a[i] });
      i++;
    }
    while (j < pb) {
      out.push({ type: 'added', text: b[j] });
      j++;
    }
    out.push({ type: 'equal', text: a[pa] });
    i = pa + 1;
    j = pb + 1;
  }
  while (i < a.length) {
    out.push({ type: 'removed', text: a[i] });
    i++;
  }
  while (j < b.length) {
    out.push({ type: 'added', text: b[j] });
    j++;
  }
  return out;
}

/** 便利函数: 一次算完整 diff segments. */
export function diffSentences(original, rewrite) {
  const a = splitUnits(original);
  const b = splitUnits(rewrite);
  const pairs = lcsAlign(a, b);
  return coalesceDiff(a, b, pairs);
}
