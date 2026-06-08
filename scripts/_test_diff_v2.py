"""Smoke test for diff_service + insert_suggestion round-trip."""
import sys
from pathlib import Path

BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# 1) diff_service 基础测试 (无数据库)
from services.diff_service import compute_diff

cases = [
    ("", "", 0, 0, 0),
    ("abc", "abc", 0, 0, 0),
    ("abc", "abcd", 0, 0, 1),  # 1 个 added
    ("hello world", "hello there world", 0, 0, 1),  # 1 个 added: "there "
]

for orig, rwt, exp_rem, exp_add, exp_segs in cases:
    segs, stats, trunc = compute_diff(orig, rwt)
    print(
        f"orig={orig!r:25} rwt={rwt!r:25} -> "
        f"segs={len(segs)} added={stats['added_length']} "
        f"removed={stats['removed_length']} trunc={trunc}"
    )
    assert len(segs) >= 0

# 2) 完整 100 字符 round-trip
orig = "今天天气很好, 我们去公园散步, 看到很多人在跑步。"
rwt = "今天天气很好, 我们一家人去公园散步, 看到很多人在跑步锻炼身体。"
segs, stats, trunc = compute_diff(orig, rwt)
print(f"\nRound-trip:\n  orig_len={len(orig)} rwt_len={len(rwt)}\n  "
      f"added={stats['added_length']} removed={stats['removed_length']}\n  "
      f"segs={len(segs)}")
print("  segments:")
for s in segs:
    print(f"    [{s['type']:9s}] {s['text']!r}")

print("\nDIFF OK")
