"""数据库访问入口（薄壳）.

历史原因:  ``database.py`` 曾经是 4089 行的"巨石文件". 修复 #1 后, 真实
业务 CRUD 已拆分到 ``backend/db/`` 包 (configs / novels / common / novel_kg /
enrichment / ai_creation / ai_kg / schema), 本文件只保留:

* 共享连接 / 事务 / 迁移 (open_db / close_db / get_db / init_db / _run_migrations / ...)
* 通用辅助 (rows_to_dicts / get_table_columns / _safe_remove 等)
* 对 ``db.*`` 业务模块的"扁平重导出", 保留所有老的
  ``from database import get_novel_by_id, ...`` 调用方式

外部 import 兼容性: 历史上 routers / services / tests 都通过
``from database import <业务函数名>`` 调用, 现在 ``database`` 仍然提供这些
名字, 不会破坏现有调用方.
"""
from __future__ import annotations

import logging

import aiosqlite

from config import DATABASE_PATH  # noqa: F401  重新导出, 供 conftest monkeypatch
from db.connection import (  # noqa: F401  重新导出
    LATEST_USER_VERSION,
    close_db,
    get_db,
    get_table_columns,
    open_db,
    rows_to_dicts,
)
from db.connection import (  # noqa: F401  兼容旧命名
    _decode_attributes,
    _decode_extras,
    _encode_attributes,
    _encode_extras,
    _get_table_columns,
    _rows_to_dicts,
    _safe_remove,
)
from db.schema import SCHEMA_STATEMENTS  # 重新导出, 兼容旧测试 / 旧引用

logger = logging.getLogger(__name__)


# ============================================================
# 迁移执行 (修复 #5)
# ============================================================
async def _get_user_version(db: aiosqlite.Connection) -> int:
    cur = await db.execute("PRAGMA user_version")
    row = await cur.fetchone()
    if not row:
        return 0
    return int(row[0] or 0)


async def _set_user_version(db: aiosqlite.Connection, version: int) -> None:
    await db.execute(f"PRAGMA user_version = {int(version)}")
    await db.commit()


async def _has_columns(
    db: aiosqlite.Connection,
    table: str,
    required_columns: list[str],
) -> bool:
    cols = await get_table_columns(db, table)
    if not cols:
        return False
    col_set = set(cols)
    return all(col in col_set for col in required_columns)


async def _is_latest_schema_already_applied(db: aiosqlite.Connection) -> bool:
    """检查未记录 user_version 的旧库是否已经处于当前最新结构."""
    required = [
        ("novels", ["summary"]),
        ("model_configs", ["capability"]),
        (
            "ai_chapter_variants",
            [
                "kg_extracted_at",
                "kg_entity_count",
                "kg_event_count",
                "superseded",
                "superseded_at",
                "generation_round",
            ],
        ),
        (
            "ai_chapters",
            [
                "kg_extracted_at",
                "kg_entity_count",
                "kg_event_count",
                "current_location",
                "compass_score",
                "compass_warnings",
                "compass_summary",
            ],
        ),
        ("ai_kg_event_relations", ["relation_type"]),
        ("ai_projects", ["themes_progress"]),
    ]
    for table, cols in required:
        if not await _has_columns(db, table, cols):
            return False
    return True


async def _run_migrations(db: aiosqlite.Connection) -> None:
    """迁移执行器 (修复 #5).

    * 迁移前先写 ``user_version = target``, 失败时回退到 ``old``;
    * 幂等: 已到达 ``LATEST_USER_VERSION`` 直接返回;
    * 兼容"老库 user_version=0 但结构已是最新": 通过
      ``_is_latest_schema_already_applied`` 同步版本.
    """
    current_version = await _get_user_version(db)
    if current_version >= LATEST_USER_VERSION:
        return
    if current_version == 0 and await _is_latest_schema_already_applied(db):
        await _set_user_version(db, LATEST_USER_VERSION)
        logger.info(
            "Migration: detected latest schema on disk, synced user_version=%s",
            LATEST_USER_VERSION,
        )
        return

    migrations = {
        1: _migrate_to_v1_schema,
    }
    applied_version = current_version
    for version in range(current_version + 1, LATEST_USER_VERSION + 1):
        runner = migrations.get(version)
        if runner is None:
            raise RuntimeError(f"未知数据库迁移版本: {version}")
        try:
            # 修复 #5: 在执行迁移前先写入 user_version 进度标记.
            await _set_user_version(db, version)
            await runner(db)
            await db.commit()
            applied_version = version
        except Exception:
            await _set_user_version(db, applied_version)
            logger.exception(
                "Migration failed at version %s, rolled user_version back to %s",
                version,
                applied_version,
            )
            raise


async def _migrate_to_v1_schema(db: aiosqlite.Connection) -> None:
    """v0.1 → v1: 把遗留库补齐到当前 latest schema.

    包含 v0.1 文档中 #1 / #3 / #16 / #41 阶段 1①②③ 需要的全部列,
    与 ``_is_latest_schema_already_applied`` 的 expected column 集合保持一致.
    """
    novel_columns = await get_table_columns(db, "novels")
    if novel_columns and "summary" not in novel_columns:
        await db.execute("ALTER TABLE novels ADD COLUMN summary TEXT")
        logger.info("Migration: added novels.summary column")

    # Drop legacy characters table (pre-knowledge-graph schema).
    char_columns = await get_table_columns(db, "characters")
    if char_columns and "entity_id" not in char_columns:
        await db.execute("DROP TABLE characters")
        logger.info("Migration: dropped legacy characters table")

    model_columns = await get_table_columns(db, "model_configs")
    if model_columns and "capability" not in model_columns:
        await db.execute(
            "ALTER TABLE model_configs ADD COLUMN capability TEXT NOT NULL DEFAULT 'chat'"
        )
        logger.info("Migration: added model_configs.capability column")

    ce_columns = await get_table_columns(db, "character_event_relations")
    if ce_columns and "properties" not in ce_columns:
        await db.execute(
            "ALTER TABLE character_event_relations ADD COLUMN properties TEXT"
        )
        logger.info(
            "Migration: added character_event_relations.properties column"
        )

    for table in (
        "characters",
        "events",
        "character_event_relations",
        "character_relations",
        "event_relations",
    ):
        cols = await get_table_columns(db, table)
        if cols and "extras" not in cols:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN extras TEXT")
            logger.info("Migration: added %s.extras column", table)

    sug_columns = await get_table_columns(db, "enrichment_suggestions")
    if sug_columns and "enrichment_intent" not in sug_columns:
        await db.execute(
            "ALTER TABLE enrichment_suggestions ADD COLUMN enrichment_intent TEXT"
        )
        logger.info(
            "Migration: added enrichment_suggestions.enrichment_intent column"
        )

    ce_columns = await get_table_columns(db, "chapter_enrichments")
    if ce_columns and "enrichment_intent" not in ce_columns:
        await db.execute(
            "ALTER TABLE chapter_enrichments ADD COLUMN enrichment_intent TEXT"
        )
        logger.info(
            "Migration: added chapter_enrichments.enrichment_intent column"
        )

    av_columns = await get_table_columns(db, "ai_chapter_variants")
    if av_columns:
        if "kg_extracted_at" not in av_columns:
            await db.execute(
                "ALTER TABLE ai_chapter_variants ADD COLUMN kg_extracted_at TIMESTAMP"
            )
            logger.info("Migration: added ai_chapter_variants.kg_extracted_at")
        if "kg_entity_count" not in av_columns:
            await db.execute(
                "ALTER TABLE ai_chapter_variants ADD COLUMN kg_entity_count INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Migration: added ai_chapter_variants.kg_entity_count")
        if "kg_event_count" not in av_columns:
            await db.execute(
                "ALTER TABLE ai_chapter_variants ADD COLUMN kg_event_count INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Migration: added ai_chapter_variants.kg_event_count")
        if "superseded" not in av_columns:
            await db.execute(
                "ALTER TABLE ai_chapter_variants ADD COLUMN superseded INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Migration: added ai_chapter_variants.superseded")
        if "superseded_at" not in av_columns:
            await db.execute(
                "ALTER TABLE ai_chapter_variants ADD COLUMN superseded_at TIMESTAMP"
            )
            logger.info("Migration: added ai_chapter_variants.superseded_at")
        if "generation_round" not in av_columns:
            await db.execute(
                "ALTER TABLE ai_chapter_variants ADD COLUMN generation_round INTEGER NOT NULL DEFAULT 1"
            )
            logger.info("Migration: added ai_chapter_variants.generation_round")

    chap_columns = await get_table_columns(db, "ai_chapters")
    if chap_columns:
        if "kg_extracted_at" not in chap_columns:
            await db.execute(
                "ALTER TABLE ai_chapters ADD COLUMN kg_extracted_at TIMESTAMP"
            )
            logger.info("Migration: added ai_chapters.kg_extracted_at")
        if "kg_entity_count" not in chap_columns:
            await db.execute(
                "ALTER TABLE ai_chapters ADD COLUMN kg_entity_count INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Migration: added ai_chapters.kg_entity_count")
        if "kg_event_count" not in chap_columns:
            await db.execute(
                "ALTER TABLE ai_chapters ADD COLUMN kg_event_count INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Migration: added ai_chapters.kg_event_count")
        if "current_location" not in chap_columns:
            await db.execute("ALTER TABLE ai_chapters ADD COLUMN current_location TEXT")
            logger.info("Migration: added ai_chapters.current_location")
        if "compass_score" not in chap_columns:
            await db.execute("ALTER TABLE ai_chapters ADD COLUMN compass_score REAL")
            logger.info("Migration: added ai_chapters.compass_score")
        if "compass_warnings" not in chap_columns:
            await db.execute("ALTER TABLE ai_chapters ADD COLUMN compass_warnings TEXT")
            logger.info("Migration: added ai_chapters.compass_warnings")
        if "compass_summary" not in chap_columns:
            await db.execute("ALTER TABLE ai_chapters ADD COLUMN compass_summary TEXT")
            logger.info("Migration: added ai_chapters.compass_summary")

    char_columns = await get_table_columns(db, "ai_kg_characters")
    if char_columns:
        new_char_cols = {
            "role": "TEXT",
            "faction": "TEXT",
            "current_location_entity_id": "TEXT",
            "status": "TEXT",
            "first_appearance_chapter_id": "INTEGER",
            "importance": "INTEGER",
            "aliases": "TEXT",
            "description": "TEXT",
        }
        for col, ty in new_char_cols.items():
            if col not in char_columns:
                await db.execute(
                    f"ALTER TABLE ai_kg_characters ADD COLUMN {col} {ty}"
                )
                logger.info("Migration: added ai_kg_characters.%s", col)

    ev_columns = await get_table_columns(db, "ai_kg_events")
    if ev_columns:
        new_ev_cols = {
            "in_story_time": "TEXT",
            "chapter_time_label": "TEXT",
            "importance": "INTEGER",
            "aliases": "TEXT",
            "description": "TEXT",
        }
        for col, ty in new_ev_cols.items():
            if col not in ev_columns:
                await db.execute(
                    f"ALTER TABLE ai_kg_events ADD COLUMN {col} {ty}"
                )
                logger.info("Migration: added ai_kg_events.%s", col)

    loc_columns = await get_table_columns(db, "ai_kg_locations")
    if loc_columns:
        new_loc_cols = {
            "aliases": "TEXT",
            "description": "TEXT",
        }
        for col, ty in new_loc_cols.items():
            if col not in loc_columns:
                await db.execute(
                    f"ALTER TABLE ai_kg_locations ADD COLUMN {col} {ty}"
                )
                logger.info("Migration: added ai_kg_locations.%s", col)

    ccrel_columns = await get_table_columns(db, "ai_kg_character_relations")
    if ccrel_columns:
        for col, ty in {
            "start_chapter_id": "INTEGER",
            "end_chapter_id": "INTEGER",
        }.items():
            if col not in ccrel_columns:
                await db.execute(
                    f"ALTER TABLE ai_kg_character_relations ADD COLUMN {col} {ty}"
                )
                logger.info("Migration: added ai_kg_character_relations.%s", col)

    eerel_columns = await get_table_columns(db, "ai_kg_event_relations")
    if eerel_columns and "relation_type" not in eerel_columns:
        await db.execute(
            "ALTER TABLE ai_kg_event_relations ADD COLUMN relation_type TEXT"
        )
        logger.info("Migration: added ai_kg_event_relations.relation_type")

    proj_columns = await get_table_columns(db, "ai_projects")
    if proj_columns and "themes_progress" not in proj_columns:
        await db.execute(
            "ALTER TABLE ai_projects ADD COLUMN themes_progress TEXT"
        )
        logger.info("Migration: added ai_projects.themes_progress")


async def init_db() -> None:
    db = await open_db()
    await _run_migrations(db)
    for stmt in SCHEMA_STATEMENTS:
        await db.execute(stmt)
    await db.commit()
    from services.prompt_service import seed_default_prompts
    await seed_default_prompts()


# ============================================================
# 业务模块的"扁平重导出"
#   - 历史代码一直 ``from database import get_novel_by_id`` 这样写
#   - 现在真实实现都在 ``db.*`` 里, 这里做 ``from db.x import *``
#   - 维持外部调用方零改动
# ============================================================
from db.configs import *  # noqa: E402, F401, F403
from db.novels import *  # noqa: E402, F401, F403
from db.common import (  # noqa: E402, F401
    _build_entity_extras,
    _build_relation_extras,
    _decode_attributes,
    _decode_extras,
    _encode_attributes,
    _encode_extras,
    _extract_aliases_from_obj,
    _merge_aliases,
    _aliases_from_db,
    _aliases_to_db,
)
from db.novel_kg import *  # noqa: E402, F401, F403
from db.enrichment import *  # noqa: E402, F401, F403
from db.ai_creation import *  # noqa: E402, F401, F403
from db.ai_kg import *  # noqa: E402, F401, F403
