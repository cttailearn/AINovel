"""手动补齐缺失的默认提示词 (CLI 工具).

适用场景: 升级到包含新分类 (如 enrichment.*) 的代码后, 旧数据库里
没有这些内置模板, 而 seed_default_prompts 只在应用下次启动时才会回填.
运行此脚本可立即补齐, 无需重启后端.

用法 (在项目根目录):
    python -m scripts.reseed_prompts
    # 或
    python scripts/reseed_prompts.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 把 backend/ 加入 sys.path, 让 services / database / config 可直接 import
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from database import init_db  # noqa: E402
from services.prompt_service import (  # noqa: E402
    DEFAULT_PROMPTS,
    reseed_default_prompts,
)


async def main() -> None:
    print("=" * 60)
    print("AINovel · 提示词补齐工具")
    print("=" * 60)
    print(f"内置默认模板总数: {len(DEFAULT_PROMPTS)}")
    print("分类: " + ", ".join(sorted({t['category'] for t in DEFAULT_PROMPTS})))
    print()

    # 确保数据库结构已就绪
    await init_db()

    summary = await reseed_default_prompts()
    print(f"补齐结果: 共 {summary['total_defaults']} 个默认模板")
    print(f"本次新增: {summary['inserted']} 个")
    if summary["inserted_keys"]:
        print("新增列表:")
        for key in summary["inserted_keys"]:
            print(f"  + {key}")
    else:
        print("所有默认模板均已存在, 无需补齐.")
    print()
    print("打开「系统设置 → 提示词管理」即可看到新增分类 (如「小说加料」「改写规则·通用」等).")


if __name__ == "__main__":
    asyncio.run(main())
