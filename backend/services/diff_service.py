"""基于 LCS 的简易 diff, 输出 [{type, text}] 段.

设计目标:
* 整章级别 (数千~数万字) 性能可接受, 不做字符级精确对齐, 按"句子 / 短语"
  为单位做对齐, 人类阅读体验更自然.
* 输出 ``unchanged / added / removed`` 三种类型, 长度衡量也保持一致.
* 对超长文本做长度截断保护, 避免阻塞事件循环.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

# 句子分隔: 中英文句末标点 + 换行
_SENT_SPLIT = re.compile(r"(?<=[。!?！？\n])")

# 软保护: 超过该字符数后, 退化为"全部标记为 added", 仅返回字数差
_MAX_CHARS = 60_000
# 段最大数量 (前端一次性渲染太多 span 会卡)
_MAX_SEGMENTS = 4_000


def _split_units(text: str) -> List[str]:
    """把文本切成用于 diff 的最小单位.

    中文/英文混排: 用句末标点 + 换行 切; 单段过长 (>120 字符) 时再切一次.
    """
    if not text:
        return []
    text = text.strip("\n")
    if not text:
        return []
    pieces: List[str] = []
    for raw in _SENT_SPLIT.split(text):
        s = raw.strip("\n")
        if not s:
            continue
        if len(s) <= 120:
            pieces.append(s)
        else:
            # 长段进一步按 ~80 字符切, 避免单段 LCS 单元过大
            step = 80
            for i in range(0, len(s), step):
                pieces.append(s[i : i + step])
    return pieces


def _lcs_table(a: List[str], b: List[str]) -> List[List[int]]:
    """O(M*N) 经典 LCS DP. 适合两侧均在数千行以内.

    对 60k+ 字符输入会触发 ``_MAX_CHARS`` 短路, 因此这里 DP 表规模可控.
    """
    m, n = len(a), len(b)
    # 用 array 模块的 'I' 节省内存 (Python list of int 也很重)
    table: List[List[int]] = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        ai = a[i]
        row = table[i]
        next_row = table[i + 1]
        for j in range(n):
            if ai == b[j]:
                next_row[j + 1] = row[j] + 1
            else:
                left = next_row[j]
                up = row[j + 1]
                next_row[j + 1] = left if left >= up else up
    return table


def _backtrack(
    table: List[List[int]], a: List[str], b: List[str]
) -> List[Tuple[str, str]]:
    """回溯得到 [(op, unit)], op in {'=' '+' '-'}; 顺序与 a+b 一致."""
    ops: List[Tuple[str, str]] = []
    i, j = len(a), len(b)
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            ops.append(("=", a[i - 1]))
            i -= 1
            j -= 1
        elif table[i - 1][j] >= table[i][j - 1]:
            ops.append(("-", a[i - 1]))
            i -= 1
        else:
            ops.append(("+", b[j - 1]))
            j -= 1
    while i > 0:
        ops.append(("-", a[i - 1]))
        i -= 1
    while j > 0:
        ops.append(("+", b[j - 1]))
        j -= 1
    ops.reverse()
    return ops


def _coalesce(ops: List[Tuple[str, str]]) -> List[Dict[str, str]]:
    """把连续同类型的 op 合并成一个段, 便于前端渲染."""
    out: List[Dict[str, str]] = []
    for op, unit in ops:
        if op == "=":
            t = "unchanged"
        elif op == "+":
            t = "added"
        else:
            t = "removed"
        if out and out[-1]["type"] == t:
            out[-1]["text"] += unit
        else:
            out.append({"type": t, "text": unit})
    # 把末尾分隔符处理: 让段落自然衔接 (例如句号跟着原文), 不强制加换行
    return out


def compute_diff(
    original: str, rewrite: str
) -> Tuple[List[Dict[str, str]], Dict[str, int], bool]:
    """返回 (segments, stats, truncated).

    * ``segments``       : [{type, text}, ...]
    * ``stats``          : {original_length, rewrite_length, added_length, removed_length}
    * ``truncated``      : 是否因长度超限而退化为简化结果
    """
    original = original or ""
    rewrite = rewrite or ""
    orig_len = len(original)
    rwt_len = len(rewrite)
    stats = {
        "original_length": orig_len,
        "rewrite_length": rwt_len,
        "added_length": 0,
        "removed_length": 0,
    }

    if orig_len + rwt_len > _MAX_CHARS * 2:
        # 双倍超限: 退化
        return (
            [
                {"type": "unchanged", "text": original[:200]},
                {"type": "added", "text": rewrite[:200]},
                {"type": "removed", "text": original[-200:] if orig_len > 200 else ""},
            ],
            stats,
            True,
        )
    a = _split_units(original)
    b = _split_units(rewrite)
    if not a and not b:
        return [], stats, False
    if not a:
        return [{"type": "added", "text": rewrite}], {**stats, "added_length": rwt_len}, False
    if not b:
        return [{"type": "removed", "text": original}], {**stats, "removed_length": orig_len}, False
    table = _lcs_table(a, b)
    ops = _backtrack(table, a, b)
    segs = _coalesce(ops)
    for seg in segs:
        if seg["type"] == "added":
            stats["added_length"] += len(seg["text"])
        elif seg["type"] == "removed":
            stats["removed_length"] += len(seg["text"])
    if len(segs) > _MAX_SEGMENTS:
        # 截断: 仅保留前 N 段
        segs = segs[:_MAX_SEGMENTS]
        return segs, stats, True
    return segs, stats, False
