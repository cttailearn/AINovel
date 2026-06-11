import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

import aiosqlite

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


SCHEMA_STATEMENTS: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS model_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        provider TEXT NOT NULL,
        model_url TEXT NOT NULL,
        api_key TEXT NOT NULL,
        model_name TEXT NOT NULL,
        capability TEXT NOT NULL DEFAULT 'chat',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS novels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '未知作者',
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        parse_rule TEXT,
        summary TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        novel_id INTEGER NOT NULL,
        chapter_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT,
        start_position INTEGER NOT NULL DEFAULT 0,
        end_position INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE,
        UNIQUE (novel_id, chapter_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        novel_id INTEGER NOT NULL,
        entity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        attributes TEXT,
        model_id INTEGER,
        extras TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE,
        FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE SET NULL,
        UNIQUE (novel_id, entity_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        novel_id INTEGER NOT NULL,
        entity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        attributes TEXT,
        model_id INTEGER,
        extras TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE,
        FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE SET NULL,
        UNIQUE (novel_id, entity_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS character_event_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        novel_id INTEGER NOT NULL,
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT NOT NULL,
        relation TEXT NOT NULL DEFAULT 'PARTICIPATES_IN',
        role TEXT,
        action TEXT,
        properties TEXT,
        extras TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS character_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        novel_id INTEGER NOT NULL,
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        properties TEXT,
        extras TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        novel_id INTEGER NOT NULL,
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        properties TEXT,
        extras TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chapters_novel ON chapters(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_novels_created ON novels(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_characters_novel ON characters(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_novel ON events(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_ce_rels_novel ON character_event_relations(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_cc_rels_novel ON character_relations(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_ee_rels_novel ON event_relations(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_characters_entity ON characters(novel_id, entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_entity ON events(novel_id, entity_id)",
    """
    CREATE TABLE IF NOT EXISTS prompt_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        system_prompt TEXT NOT NULL DEFAULT '',
        user_prompt_template TEXT NOT NULL DEFAULT '',
        temperature REAL NOT NULL DEFAULT 0.3,
        max_tokens INTEGER NOT NULL DEFAULT 2400,
        is_builtin INTEGER NOT NULL DEFAULT 0,
        is_enabled INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_prompt_templates_category ON prompt_templates(category)",
    """
    CREATE TABLE IF NOT EXISTS chapter_enrichments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        novel_id INTEGER NOT NULL,
        chapter_id INTEGER NOT NULL,
        summary TEXT,
        summary_status TEXT NOT NULL DEFAULT 'pending',
        summary_error TEXT,
        summary_model_id INTEGER,
        recognition_json TEXT,
        recognition_status TEXT NOT NULL DEFAULT 'pending',
        recognition_error TEXT,
        recognition_model_id INTEGER,
        rewrite_text TEXT,
        rewrite_status TEXT NOT NULL DEFAULT 'pending',
        rewrite_error TEXT,
        rewrite_model_id INTEGER,
        scene_tag TEXT,
        enrichment_intent TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        error TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE,
        FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
        UNIQUE (chapter_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_enrichments_novel ON chapter_enrichments(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_enrichments_status ON chapter_enrichments(status)",
    """
    CREATE TABLE IF NOT EXISTS enrichment_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL,
        novel_id INTEGER NOT NULL,
        enrichment_id INTEGER,
        original_snapshot TEXT NOT NULL,
        rewrite_text TEXT NOT NULL,
        model_id INTEGER,
        summary_snapshot TEXT,
        recognition_snapshot TEXT,
        scene_tag TEXT,
        enrichment_intent TEXT,
        status TEXT NOT NULL DEFAULT 'applied',
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reverted_at TIMESTAMP,
        FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE,
        FOREIGN KEY (enrichment_id) REFERENCES chapter_enrichments(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_suggestions_chapter ON enrichment_suggestions(chapter_id)",
    "CREATE INDEX IF NOT EXISTS idx_suggestions_status ON enrichment_suggestions(status)",
    # ============================================================
    # AI 小说创作 (AI Creation) — 与 novels + 加料 物理隔离的独立子模块
    # ============================================================
    """
    CREATE TABLE IF NOT EXISTS ai_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        genre TEXT NOT NULL DEFAULT '',
        worldview TEXT NOT NULL DEFAULT '',
        outline TEXT NOT NULL DEFAULT '',
        initial_concepts TEXT,
        style_pref TEXT,
        model_id INTEGER,
        current_chapter_no INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'draft',
        themes_progress TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_projects_created ON ai_projects(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ai_projects_status ON ai_projects(status)",
    """
    CREATE TABLE IF NOT EXISTS ai_chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        chapter_no INTEGER NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        user_intent TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',
        selected_variant_id INTEGER,
        final_content TEXT,
        word_count INTEGER NOT NULL DEFAULT 0,
        kg_extracted INTEGER NOT NULL DEFAULT 0,
        current_location TEXT,
        compass_score REAL,
        compass_warnings TEXT,
        compass_summary TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        UNIQUE (project_id, chapter_no)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_chapters_project ON ai_chapters(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_chapters_status ON ai_chapters(status)",
    """
    CREATE TABLE IF NOT EXISTS ai_chapter_variants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL,
        variant_index INTEGER NOT NULL,
        planner_direction TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        focus_summary TEXT NOT NULL DEFAULT '',
        kg_diff TEXT,
        critic_report TEXT,
        score REAL NOT NULL DEFAULT 0,
        model_id INTEGER,
        kg_extracted_at TIMESTAMP,
        kg_entity_count INTEGER NOT NULL DEFAULT 0,
        kg_event_count INTEGER NOT NULL DEFAULT 0,
        superseded INTEGER NOT NULL DEFAULT 0,
        superseded_at TIMESTAMP,
        generation_round INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (chapter_id) REFERENCES ai_chapters(id) ON DELETE CASCADE,
        UNIQUE (chapter_id, variant_index)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_variants_chapter ON ai_chapter_variants(chapter_id)",
    # ---- AI 创作专用知识图谱 (与现有 novels KG 物理隔离) ----
    """
    CREATE TABLE IF NOT EXISTS ai_kg_characters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        entity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        attributes TEXT,
        source_chapter_id INTEGER,
        model_id INTEGER,
        extras TEXT,
        role TEXT,
        faction TEXT,
        current_location_entity_id TEXT,
        status TEXT,
        first_appearance_chapter_id INTEGER,
        importance INTEGER,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (source_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL,
        FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE SET NULL,
        UNIQUE (project_id, entity_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_characters_project ON ai_kg_characters(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_characters_entity ON ai_kg_characters(project_id, entity_id)",
    """
    CREATE TABLE IF NOT EXISTS ai_kg_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        entity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        attributes TEXT,
        source_chapter_id INTEGER,
        model_id INTEGER,
        extras TEXT,
        in_story_time TEXT,
        chapter_time_label TEXT,
        importance INTEGER,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (source_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL,
        FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE SET NULL,
        UNIQUE (project_id, entity_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_events_project ON ai_kg_events(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_events_entity ON ai_kg_events(project_id, entity_id)",
    """
    CREATE TABLE IF NOT EXISTS ai_kg_character_event_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT NOT NULL,
        relation TEXT NOT NULL DEFAULT 'PARTICIPATES_IN',
        role TEXT,
        action TEXT,
        properties TEXT,
        extras TEXT,
        source_chapter_id INTEGER,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (source_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_ce_rels_project ON ai_kg_character_event_relations(project_id)",
    """
    CREATE TABLE IF NOT EXISTS ai_kg_character_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        properties TEXT,
        extras TEXT,
        source_chapter_id INTEGER,
        start_chapter_id INTEGER,
        end_chapter_id INTEGER,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (source_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_cc_rels_project ON ai_kg_character_relations(project_id)",
    """
    CREATE TABLE IF NOT EXISTS ai_kg_event_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        properties TEXT,
        extras TEXT,
        source_chapter_id INTEGER,
        relation_type TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (source_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_ee_rels_project ON ai_kg_event_relations(project_id)",
    # ============================================================
    # v0.3.x 新增表: 地点 / 伏笔线索 / 出场记录
    # ============================================================
    """
    CREATE TABLE IF NOT EXISTS ai_kg_locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        entity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        location_type TEXT,                       -- 城市 / 建筑 / 秘境 / 区域 / 异空间
        attributes TEXT,                          -- {坐标, 气候, 控制势力, 禁制, 描述}
        source_chapter_id INTEGER,
        model_id INTEGER,
        extras TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (source_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL,
        FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE SET NULL,
        UNIQUE (project_id, entity_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_locations_project ON ai_kg_locations(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_locations_entity ON ai_kg_locations(project_id, entity_id)",
    """
    CREATE TABLE IF NOT EXISTS ai_kg_plot_threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        thread_id TEXT NOT NULL,
        title TEXT NOT NULL,
        thread_type TEXT,                          -- 伏笔 / 阴谋 / 角色弧 / 主题弧 / 承诺
        status TEXT,                               -- open / hinting / resolving / resolved / dropped
        priority INTEGER,                          -- 1..5, 5=主线
        introduced_chapter_id INTEGER,
        resolved_chapter_id INTEGER,
        related_entity_ids TEXT,                   -- JSON: ["char_001", "evt_007"]
        notes TEXT,
        source_chapter_id INTEGER,
        model_id INTEGER,
        extras TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (introduced_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL,
        FOREIGN KEY (resolved_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL,
        FOREIGN KEY (source_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL,
        FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE SET NULL,
        UNIQUE (project_id, thread_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_threads_project ON ai_kg_plot_threads(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_threads_status ON ai_kg_plot_threads(project_id, status)",
    """
    CREATE TABLE IF NOT EXISTS ai_kg_character_appearances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        entity_id TEXT NOT NULL,                    -- 引用 ai_kg_characters.entity_id
        chapter_id INTEGER NOT NULL,
        role TEXT,                                  -- 主角 / 出场 / 提及 / 回忆
        importance INTEGER,                         -- 1..5
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (chapter_id) REFERENCES ai_chapters(id) ON DELETE CASCADE,
        UNIQUE (project_id, entity_id, chapter_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_appearances_chapter ON ai_kg_character_appearances(chapter_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_appearances_entity ON ai_kg_character_appearances(entity_id)",
]


async def init_db() -> None:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        # Run migrations FIRST so legacy tables are dropped/reshaped
        # before any new CREATE INDEX statements reference their columns.
        await _run_migrations(db)
        for stmt in SCHEMA_STATEMENTS:
            await db.execute(stmt)
        await db.commit()
    # Seed default AI prompt templates if not present.
    from services.prompt_service import seed_default_prompts
    await seed_default_prompts()


async def _run_migrations(db: aiosqlite.Connection) -> None:
    novel_columns = await _get_table_columns(db, "novels")
    if novel_columns and "summary" not in novel_columns:
        await db.execute("ALTER TABLE novels ADD COLUMN summary TEXT")
        logger.info("Migration: added novels.summary column")

    # Drop legacy characters table (pre-knowledge-graph schema).
    char_columns = await _get_table_columns(db, "characters")
    if char_columns and "entity_id" not in char_columns:
        await db.execute("DROP TABLE characters")
        logger.info("Migration: dropped legacy characters table")

    # Add capability column to model_configs if missing.
    model_columns = await _get_table_columns(db, "model_configs")
    if model_columns and "capability" not in model_columns:
        await db.execute(
            "ALTER TABLE model_configs ADD COLUMN capability TEXT NOT NULL DEFAULT 'chat'"
        )
        logger.info("Migration: added model_configs.capability column")

    # Add properties column to character_event_relations so we can
    # store the full LLM-emitted property blob (时间 / 地点 / 情绪 /
    # 动机 / ...) alongside the legacy role / action shortcuts.
    ce_columns = await _get_table_columns(db, "character_event_relations")
    if ce_columns and "properties" not in ce_columns:
        await db.execute(
            "ALTER TABLE character_event_relations ADD COLUMN properties TEXT"
        )
        logger.info(
            "Migration: added character_event_relations.properties column"
        )

    # Add extras column to all 5 KG tables for evidence / confidence
    # / chunk_id (升级 evidence 数据结构后需要落库).
    for table in (
        "characters",
        "events",
        "character_event_relations",
        "character_relations",
        "event_relations",
    ):
        cols = await _get_table_columns(db, table)
        if cols and "extras" not in cols:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN extras TEXT")
            logger.info("Migration: added %s.extras column", table)

    # v0.2.1: enrichment_suggestions 加 enrichment_intent 列 (升级加料工坊后)
    sug_columns = await _get_table_columns(db, "enrichment_suggestions")
    if sug_columns and "enrichment_intent" not in sug_columns:
        await db.execute(
            "ALTER TABLE enrichment_suggestions ADD COLUMN enrichment_intent TEXT"
        )
        logger.info(
            "Migration: added enrichment_suggestions.enrichment_intent column"
        )

    # v0.2.1: chapter_enrichments 加 enrichment_intent 列 (持久化用户的加料需求)
    ce_columns = await _get_table_columns(db, "chapter_enrichments")
    if ce_columns and "enrichment_intent" not in ce_columns:
        await db.execute(
            "ALTER TABLE chapter_enrichments ADD COLUMN enrichment_intent TEXT"
        )
        logger.info(
            "Migration: added chapter_enrichments.enrichment_intent column"
        )

    # ============================================================
    # v0.3.x: 知识图谱架构升级 (方案 docs/ai-creation-kg-architecture.md)
    # ============================================================
    # ① ai_chapter_variants 加 kg_extracted_at + 计数
    av_columns = await _get_table_columns(db, "ai_chapter_variants")
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
        # P0-#3 版本历史: 重新生成时旧变体不删, 标 superseded
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

    # ④ ai_chapters 加当前主场景 + compass 评分
    chap_columns = await _get_table_columns(db, "ai_chapters")
    if chap_columns:
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

    # ⑥ ai_kg_characters 加结构化字段
    char_columns = await _get_table_columns(db, "ai_kg_characters")
    if char_columns:
        new_char_cols = {
            "role": "TEXT",  # 主角 / 配角 / 路人 / 反派
            "faction": "TEXT",  # 所属势力
            "current_location_entity_id": "TEXT",  # 引用 ai_kg_locations.entity_id
            "status": "TEXT",  # 存活 / 失踪 / 死亡 / 转生
            "first_appearance_chapter_id": "INTEGER",
            "importance": "INTEGER",  # 1..5
        }
        for col, ty in new_char_cols.items():
            if col not in char_columns:
                await db.execute(
                    f"ALTER TABLE ai_kg_characters ADD COLUMN {col} {ty}"
                )
                logger.info("Migration: added ai_kg_characters.%s", col)

    # ⑥ ai_kg_events 加结构化字段
    ev_columns = await _get_table_columns(db, "ai_kg_events")
    if ev_columns:
        new_ev_cols = {
            "in_story_time": "TEXT",  # "第3年 暮春"
            "chapter_time_label": "TEXT",  # "第3章 夜"
            "importance": "INTEGER",
        }
        for col, ty in new_ev_cols.items():
            if col not in ev_columns:
                await db.execute(
                    f"ALTER TABLE ai_kg_events ADD COLUMN {col} {ty}"
                )
                logger.info("Migration: added ai_kg_events.%s", col)

    # ⑥ ai_kg_character_relations 加时间窗口
    ccrel_columns = await _get_table_columns(db, "ai_kg_character_relations")
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

    # ⑥ ai_kg_event_relations 加关系类型 (causal/temporal/spatial)
    eerel_columns = await _get_table_columns(db, "ai_kg_event_relations")
    if eerel_columns and "relation_type" not in eerel_columns:
        await db.execute(
            "ALTER TABLE ai_kg_event_relations ADD COLUMN relation_type TEXT"
        )
        logger.info("Migration: added ai_kg_event_relations.relation_type")

    # ⑨ ai_projects 加 themes_progress
    proj_columns = await _get_table_columns(db, "ai_projects")
    if proj_columns and "themes_progress" not in proj_columns:
        await db.execute(
            "ALTER TABLE ai_projects ADD COLUMN themes_progress TEXT"
        )
        logger.info("Migration: added ai_projects.themes_progress")


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute("PRAGMA foreign_keys = ON")
        yield db
    finally:
        await db.close()


def _rows_to_dicts(rows: Iterable[aiosqlite.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


async def _get_table_columns(
    db: aiosqlite.Connection, table: str
) -> List[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return [row[1] for row in rows]


async def get_all_configs() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM model_configs ORDER BY created_at DESC, id DESC"
        )
        return _rows_to_dicts(await cur.fetchall())


async def get_enabled_configs() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM model_configs WHERE enabled = 1 "
            "ORDER BY created_at DESC, id DESC"
        )
        return _rows_to_dicts(await cur.fetchall())


async def get_enabled_configs_by_capability(capability: str) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM model_configs WHERE enabled = 1 AND capability = ? "
            "ORDER BY created_at DESC, id DESC",
            (capability,),
        )
        return _rows_to_dicts(await cur.fetchall())


async def get_config_by_id(config_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM model_configs WHERE id = ?", (config_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def save_config(
    name: str,
    provider: str,
    model_url: str,
    api_key: str,
    model_name: str,
    enabled: int = 1,
    capability: str = "chat",
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO model_configs
                (name, provider, model_url, api_key, model_name, capability, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, provider, model_url, api_key, model_name, capability, enabled),
        )
        await db.commit()
        return cur.lastrowid or 0


async def update_config(
    config_id: int,
    name: str,
    provider: str,
    model_url: str,
    api_key: str,
    model_name: str,
    enabled: int,
    capability: str = "chat",
) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE model_configs SET
                name = ?,
                provider = ?,
                model_url = ?,
                api_key = ?,
                model_name = ?,
                capability = ?,
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, provider, model_url, api_key, model_name, capability, enabled, config_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def toggle_config_enabled(config_id: int, enabled: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE model_configs SET
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (enabled, config_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_config_by_id(config_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM model_configs WHERE id = ?", (config_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def save_novel(
    title: str,
    author: str,
    filename: str,
    file_path: str,
    file_size: int,
    summary: Optional[str] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO novels
                (title, author, filename, file_path, file_size, status, summary)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (title, author, filename, file_path, file_size, summary),
        )
        await db.commit()
        return cur.lastrowid or 0


async def update_novel_title_author(
    novel_id: int, title: str, author: str
) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE novels SET
                title = ?, author = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, author, novel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_novel_status(novel_id: int, status: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE novels SET
                status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, novel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_novel_parse_rule(novel_id: int, rule: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE novels SET
                parse_rule = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (rule, novel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_novel_file_path(novel_id: int, file_path: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE novels SET
                file_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (file_path, novel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_novel_by_id(novel_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM novels WHERE id = ?", (novel_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_all_novels() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT n.*, COUNT(c.id) AS chapter_count
            FROM novels n
            LEFT JOIN chapters c ON n.id = c.novel_id
            GROUP BY n.id
            ORDER BY n.created_at DESC, n.id DESC
            """
        )
        return _rows_to_dicts(await cur.fetchall())


async def delete_novel_by_id(novel_id: int) -> bool:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
        cur = await db.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
        await db.commit()
        return cur.rowcount > 0


async def replace_chapters(
    novel_id: int, chapters: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
        if not chapters:
            await db.commit()
            return []
        inserted: List[Dict[str, Any]] = []
        for c in chapters:
            cur = await db.execute(
                """
                INSERT INTO chapters
                    (novel_id, chapter_number, title,
                     start_position, end_position, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    c["chapter_number"],
                    c["title"],
                    c["start_position"],
                    c["end_position"],
                    c.get("content"),
                ),
            )
            inserted.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "chapter_number": c["chapter_number"],
                    "title": c["title"],
                    "start_position": c["start_position"],
                    "end_position": c["end_position"],
                }
            )
        await db.commit()
        return inserted


async def get_chapters_by_novel(novel_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, novel_id, chapter_number, title,
                   start_position, end_position, created_at
            FROM chapters
            WHERE novel_id = ?
            ORDER BY chapter_number
            """,
            (novel_id,),
        )
        return _rows_to_dicts(await cur.fetchall())


async def update_chapter(
    novel_id: int,
    chapter_id: int,
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> bool:
    """更新章节的标题/正文。

    仅修改传入的字段,未传入的保持原值。编辑后内容不再回退到文件切片,
    因此把 ``start_position`` 置 0、``end_position`` 设为新内容长度。
    """
    fields: List[str] = []
    values: List[Any] = []
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if content is not None:
        fields.append("content = ?")
        # 同步起止位置: 编辑后的内容不再回退到文件切片
        fields.append("start_position = 0")
        fields.append("end_position = ?")
        values.append(len(content))
        values.append(len(content))
    if not fields:
        return False
    values.extend([chapter_id, novel_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE chapters SET {', '.join(fields)} "
            "WHERE id = ? AND novel_id = ?",
            values,
        )
        await db.commit()
        return cur.rowcount > 0


async def get_chapter_with_file(
    novel_id: int, chapter_id: int
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT c.*, n.file_path AS _file_path
            FROM chapters c
            JOIN novels n ON c.novel_id = n.id
            WHERE c.id = ? AND c.novel_id = ?
            """,
            (chapter_id, novel_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["file_path"] = data.pop("_file_path", None)
        return data


def _safe_remove(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning("Failed to remove file %s: %s", path, exc)


def _decode_attributes(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _encode_attributes(value: Any) -> str:
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _encode_extras(value: Any) -> str:
    """extras 列的 JSON 编码, 与 _encode_attributes 一致但语义独立, 便于将来拆分."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _decode_extras(raw: Any) -> Dict[str, Any]:
    """extras 列的 JSON 解码, 兼容旧库 (无该列 / 字段为空) 情况."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _build_entity_extras(obj: Dict[str, Any]) -> Dict[str, Any]:
    """从 LLM 抽出的实体 dict 抽取 evidence / confidence / chunk_id.

    支持:
    * obj["extras"] 已经是 dict (优先)
    * obj["evidence"] 是 str 或 List[dict] (EvidenceSpan 列表)
    * obj["confidence"] 是数字
    * obj["chunk_id"] 字符串
    """
    extras: Dict[str, Any] = {}
    if "extras" in obj and isinstance(obj["extras"], dict):
        extras.update(obj["extras"])
    ev = obj.get("evidence")
    if ev:
        if isinstance(ev, str):
            extras["evidence"] = [{
                "quote": ev, "chunk_id": obj.get("chunk_id", ""),
                "start": None, "end": None, "strategy": "fallback",
            }]
        elif isinstance(ev, list):
            extras["evidence"] = ev
    if "confidence" in obj:
        extras["confidence"] = obj.get("confidence")
    if obj.get("chunk_id"):
        extras.setdefault("chunk_id", obj["chunk_id"])
    return extras


def _build_relation_extras(obj: Dict[str, Any]) -> Dict[str, Any]:
    """关系类的 extras 构造: 同上, 但 evidence 既可来自单条 span,
    也可来自两个端点的 span 合并(由 orchestrator 负责)."""
    return _build_entity_extras(obj)


# ---------------------------------------------------------------------------
# Knowledge graph CRUD
# ---------------------------------------------------------------------------


async def delete_knowledge_graph(novel_id: int) -> Dict[str, int]:
    """原子清空指定小说的全部知识图谱.

    返回每张表的删除行数, 便于前端展示"已删除 X 人物 / Y 事件 / Z 关系".
    """
    counts: Dict[str, int] = {}
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for table in (
            "character_event_relations",
            "character_relations",
            "event_relations",
            "events",
            "characters",
        ):
            cur = await db.execute(
                f"DELETE FROM {table} WHERE novel_id = ?", (novel_id,)
            )
            counts[table] = cur.rowcount or 0
        await db.commit()
    return counts


# ---------------------------------------------------------------------------
# Knowledge graph CRUD
# ---------------------------------------------------------------------------


async def replace_knowledge_graph(
    novel_id: int,
    *,
    characters: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    character_event_relations: List[Dict[str, Any]],
    character_relations: List[Dict[str, Any]],
    event_relations: List[Dict[str, Any]],
    model_id: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Atomically replace the full knowledge graph for a novel."""
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM character_event_relations WHERE novel_id = ?", (novel_id,))
        await db.execute("DELETE FROM character_relations WHERE novel_id = ?", (novel_id,))
        await db.execute("DELETE FROM event_relations WHERE novel_id = ?", (novel_id,))
        await db.execute("DELETE FROM events WHERE novel_id = ?", (novel_id,))
        await db.execute("DELETE FROM characters WHERE novel_id = ?", (novel_id,))

        stored_chars: List[Dict[str, Any]] = []
        for c in characters:
            extras = c.get("extras") or _build_entity_extras(c)
            cur = await db.execute(
                """
                INSERT INTO characters
                    (novel_id, entity_id, name, attributes, model_id, extras)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(c.get("entity_id") or c.get("id") or "").strip(),
                    str(c.get("name", "")).strip()[:200] or "未命名",
                    _encode_attributes(c.get("attributes") or {}),
                    model_id,
                    _encode_extras(extras),
                ),
            )
            stored_chars.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "entity_id": str(c.get("entity_id") or c.get("id") or "").strip(),
                    "name": str(c.get("name", "")).strip(),
                    "attributes": c.get("attributes") or {},
                    "model_id": model_id,
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        stored_events: List[Dict[str, Any]] = []
        for e in events:
            extras = e.get("extras") or _build_entity_extras(e)
            cur = await db.execute(
                """
                INSERT INTO events
                    (novel_id, entity_id, name, attributes, model_id, extras)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(e.get("entity_id") or e.get("id") or "").strip(),
                    str(e.get("name", "")).strip()[:200] or "未命名事件",
                    _encode_attributes(e.get("attributes") or {}),
                    model_id,
                    _encode_extras(extras),
                ),
            )
            stored_events.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "entity_id": str(e.get("entity_id") or e.get("id") or "").strip(),
                    "name": str(e.get("name", "")).strip(),
                    "attributes": e.get("attributes") or {},
                    "model_id": model_id,
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        stored_ce: List[Dict[str, Any]] = []
        for r in character_event_relations:
            properties = r.get("properties") if isinstance(r.get("properties"), dict) else {}
            extras = r.get("extras") or _build_relation_extras(r)
            cur = await db.execute(
                """
                INSERT INTO character_event_relations
                    (novel_id, source_entity_id, target_entity_id,
                     relation, role, action, properties, extras)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(r.get("source") or r.get("source_entity_id") or "").strip(),
                    str(r.get("target") or r.get("target_entity_id") or "").strip(),
                    str(r.get("relation") or "PARTICIPATES_IN").strip() or "PARTICIPATES_IN",
                    (r.get("role") or None),
                    (r.get("action") or None),
                    _encode_attributes(properties),
                    _encode_extras(extras),
                ),
            )
            stored_ce.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "source_entity_id": str(r.get("source") or "").strip(),
                    "target_entity_id": str(r.get("target") or "").strip(),
                    "relation": str(r.get("relation") or "PARTICIPATES_IN").strip(),
                    "role": r.get("role") or None,
                    "action": r.get("action") or None,
                    "properties": properties,
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        stored_cc: List[Dict[str, Any]] = []
        for r in character_relations:
            extras = r.get("extras") or _build_relation_extras(r)
            cur = await db.execute(
                """
                INSERT INTO character_relations
                    (novel_id, source_entity_id, target_entity_id,
                     relation, properties, extras)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(r.get("source") or r.get("source_entity_id") or "").strip(),
                    str(r.get("target") or r.get("target_entity_id") or "").strip(),
                    str(r.get("relation") or "").strip() or "关联",
                    _encode_attributes(r.get("properties") or {}),
                    _encode_extras(extras),
                ),
            )
            stored_cc.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "source_entity_id": str(r.get("source") or "").strip(),
                    "target_entity_id": str(r.get("target") or "").strip(),
                    "relation": str(r.get("relation") or "").strip() or "关联",
                    "properties": r.get("properties") or {},
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        stored_ee: List[Dict[str, Any]] = []
        for r in event_relations:
            extras = r.get("extras") or _build_relation_extras(r)
            cur = await db.execute(
                """
                INSERT INTO event_relations
                    (novel_id, source_entity_id, target_entity_id,
                     relation, properties, extras)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(r.get("source") or r.get("source_entity_id") or "").strip(),
                    str(r.get("target") or r.get("target_entity_id") or "").strip(),
                    str(r.get("relation") or "").strip() or "关联",
                    _encode_attributes(r.get("properties") or {}),
                    _encode_extras(extras),
                ),
            )
            stored_ee.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "source_entity_id": str(r.get("source") or "").strip(),
                    "target_entity_id": str(r.get("target") or "").strip(),
                    "relation": str(r.get("relation") or "").strip() or "关联",
                    "properties": r.get("properties") or {},
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        await db.commit()
        return {
            "characters": stored_chars,
            "events": stored_events,
            "character_event_relations": stored_ce,
            "character_relations": stored_cc,
            "event_relations": stored_ee,
        }


async def get_knowledge_graph(novel_id: int) -> Dict[str, List[Dict[str, Any]]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, novel_id, entity_id, name, attributes,
                   model_id, extras, created_at, updated_at
            FROM characters WHERE novel_id = ? ORDER BY entity_id
            """,
            (novel_id,),
        )
        characters: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            characters.append(row)

        cur = await db.execute(
            """
            SELECT id, novel_id, entity_id, name, attributes,
                   model_id, extras, created_at, updated_at
            FROM events WHERE novel_id = ? ORDER BY entity_id
            """,
            (novel_id,),
        )
        events: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            events.append(row)

        cur = await db.execute(
            """
            SELECT id, novel_id, source_entity_id, target_entity_id,
                   relation, role, action, properties, extras
            FROM character_event_relations WHERE novel_id = ?
            """,
            (novel_id,),
        )
        ce_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            ce_relations.append(row)

        cur = await db.execute(
            """
            SELECT id, novel_id, source_entity_id, target_entity_id,
                   relation, properties, extras
            FROM character_relations WHERE novel_id = ?
            """,
            (novel_id,),
        )
        cc_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            cc_relations.append(row)

        cur = await db.execute(
            """
            SELECT id, novel_id, source_entity_id, target_entity_id,
                   relation, properties, extras
            FROM event_relations WHERE novel_id = ?
            """,
            (novel_id,),
        )
        ee_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            ee_relations.append(row)

    # ④ locations
    cur = await db.execute(
        """
        SELECT id, project_id, entity_id, name, location_type, attributes,
               source_chapter_id, model_id, extras, created_at, updated_at
        FROM ai_kg_locations WHERE project_id = ? ORDER BY name
        """,
        (project_id,),
    )
    locations: List[Dict[str, Any]] = []
    for r in await cur.fetchall():
        row = dict(r)
        row["attributes"] = _decode_attributes(row.get("attributes"))
        row["extras"] = _decode_extras(row.get("extras"))
        locations.append(row)

    # ⑤ plot_threads (open/hinting 优先)
    cur = await db.execute(
        """
        SELECT id, project_id, thread_id, title, thread_type, status, priority,
               introduced_chapter_id, resolved_chapter_id, related_entity_ids,
               notes, source_chapter_id, model_id, created_at, updated_at
        FROM ai_kg_plot_threads WHERE project_id = ?
        ORDER BY
            CASE status WHEN 'open' THEN 0 WHEN 'hinting' THEN 1
                        WHEN 'resolving' THEN 2 WHEN 'resolved' THEN 3
                        WHEN 'dropped' THEN 4 ELSE 5 END,
            priority DESC, created_at ASC
        """,
        (project_id,),
    )
    threads: List[Dict[str, Any]] = []
    for r in await cur.fetchall():
        row = dict(r)
        if row.get("related_entity_ids"):
            try:
                row["related_entity_ids"] = json.loads(row["related_entity_ids"])
            except (TypeError, ValueError):
                row["related_entity_ids"] = []
        threads.append(row)

    return {
        "characters": characters,
        "events": events,
        "locations": locations,
        "plot_threads": threads,
        "character_event_relations": ce_relations,
        "character_relations": cc_relations,
        "event_relations": ee_relations,
    }


async def get_kg_stats(novel_id: int) -> Dict[str, int]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM characters WHERE novel_id = ?", (novel_id,)
        )
        char_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM events WHERE novel_id = ?", (novel_id,)
        )
        event_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM character_event_relations WHERE novel_id = ?",
            (novel_id,),
        )
        ce_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM character_relations WHERE novel_id = ?",
            (novel_id,),
        )
        cc_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM event_relations WHERE novel_id = ?",
            (novel_id,),
        )
        ee_count = (await cur.fetchone())[0]
    return {
        "characters": char_count,
        "events": event_count,
        "participations": ce_count,
        "character_relations": cc_count,
        "event_relations": ee_count,
    }


# ---------------------------------------------------------------------------
# Novel enrichment (小说加料)
# ---------------------------------------------------------------------------


def _decode_recognition_json(raw: Optional[str]) -> Dict[str, Any]:
    """recognition_json 列的 JSON 解码, 兼容空/坏数据."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _encode_recognition_json(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _row_to_enrichment(row: aiosqlite.Row) -> Dict[str, Any]:
    data = dict(row)
    data["recognition"] = _decode_recognition_json(data.get("recognition_json"))
    return data


async def upsert_enrichment(
    *,
    novel_id: int,
    chapter_id: int,
    summary: Optional[str] = None,
    summary_status: Optional[str] = None,
    summary_error: Optional[str] = None,
    summary_model_id: Optional[int] = None,
    recognition: Optional[Dict[str, Any]] = None,
    recognition_status: Optional[str] = None,
    recognition_error: Optional[str] = None,
    recognition_model_id: Optional[int] = None,
    rewrite_text: Optional[str] = None,
    rewrite_status: Optional[str] = None,
    rewrite_error: Optional[str] = None,
    rewrite_model_id: Optional[int] = None,
    scene_tag: Optional[str] = None,
    enrichment_intent: Optional[str] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """按需更新 chapter_enrichments 的某些字段, 缺失则保留原值.

    仅在至少传入了 1 个可写字段时才执行写入. 三个步骤独立可写.
    """
    sets: List[str] = []
    values: List[Any] = []
    if summary is not None:
        sets.append("summary = ?")
        values.append(summary)
    if summary_status is not None:
        sets.append("summary_status = ?")
        values.append(summary_status)
    if summary_error is not None:
        sets.append("summary_error = ?")
        values.append(summary_error)
    if summary_model_id is not None:
        sets.append("summary_model_id = ?")
        values.append(int(summary_model_id))
    if recognition is not None:
        sets.append("recognition_json = ?")
        values.append(_encode_recognition_json(recognition))
    if recognition_status is not None:
        sets.append("recognition_status = ?")
        values.append(recognition_status)
    if recognition_error is not None:
        sets.append("recognition_error = ?")
        values.append(recognition_error)
    if recognition_model_id is not None:
        sets.append("recognition_model_id = ?")
        values.append(int(recognition_model_id))
    if rewrite_text is not None:
        sets.append("rewrite_text = ?")
        values.append(rewrite_text)
    if rewrite_status is not None:
        sets.append("rewrite_status = ?")
        values.append(rewrite_status)
    if rewrite_error is not None:
        sets.append("rewrite_error = ?")
        values.append(rewrite_error)
    if rewrite_model_id is not None:
        sets.append("rewrite_model_id = ?")
        values.append(int(rewrite_model_id))
    if scene_tag is not None:
        sets.append("scene_tag = ?")
        values.append(scene_tag)
    if enrichment_intent is not None:
        sets.append("enrichment_intent = ?")
        values.append(enrichment_intent)
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if error is not None:
        sets.append("error = ?")
        values.append(error)
    if not sets:
        row = await get_enrichment_by_chapter(chapter_id)
        if row:
            return row
        return {}
    # column_names 仅取写入列 (不含 updated_at 这种 SQL 片段)
    column_names = [s.split(" = ")[0] for s in sets]
    sets.append("updated_at = CURRENT_TIMESTAMP")
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "SELECT id FROM chapter_enrichments WHERE chapter_id = ?",
            (chapter_id,),
        )
        row = await cur.fetchone()
        if row:
            await db.execute(
                f"UPDATE chapter_enrichments SET {', '.join(sets)} "
                "WHERE id = ?",
                (*values, row["id"]),
            )
        else:
            placeholders = ", ".join(["?"] * len(values))
            await db.execute(
                f"INSERT INTO chapter_enrichments "
                f"(novel_id, chapter_id, {', '.join(column_names)}) "
                f"VALUES (?, ?, {placeholders})",
                (novel_id, chapter_id, *values),
            )
        await db.commit()
    return await get_enrichment_by_chapter(chapter_id) or {}


async def get_enrichment_by_chapter(chapter_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM chapter_enrichments WHERE chapter_id = ?
            """,
            (chapter_id,),
        )
        row = await cur.fetchone()
        return _row_to_enrichment(row) if row else None


async def list_enrichment_by_novel(novel_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM chapter_enrichments WHERE novel_id = ?
            """,
            (novel_id,),
        )
        rows = await cur.fetchall()
    return [_row_to_enrichment(r) for r in rows]


async def list_failed_chapter_ids(novel_id: int) -> List[int]:
    """返回任意步骤失败的章节 ID, 用于「重试失败章节」按钮."""
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT chapter_id FROM chapter_enrichments
            WHERE novel_id = ?
              AND (
                summary_status = 'failed'
                OR recognition_status = 'failed'
                OR rewrite_status = 'failed'
              )
            """,
            (novel_id,),
        )
        rows = await cur.fetchall()
    return [int(r["chapter_id"]) for r in rows]


async def reset_novel_enrichments(novel_id: int) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM chapter_enrichments WHERE novel_id = ?",
            (novel_id,),
        )
        await db.commit()
    return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# enrichment_suggestions CRUD
# ---------------------------------------------------------------------------


async def insert_suggestion(
    *,
    chapter_id: int,
    novel_id: int,
    original_snapshot: str,
    rewrite_text: str,
    enrichment_id: Optional[int] = None,
    model_id: Optional[int] = None,
    summary_snapshot: Optional[str] = None,
    recognition_snapshot: Optional[str] = None,
    scene_tag: Optional[str] = None,
    enrichment_intent: Optional[str] = None,
    status: str = "applied",
) -> int:
    """新增一条加料应用记录.

    业务规则: 同时把同 chapter 当前的 applied 改为 superseded, 保留历史链.
    """
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            UPDATE enrichment_suggestions
            SET status = 'superseded'
            WHERE chapter_id = ? AND status = 'applied'
            """,
            (chapter_id,),
        )
        cur = await db.execute(
            """
            INSERT INTO enrichment_suggestions
                (chapter_id, novel_id, enrichment_id, original_snapshot,
                 rewrite_text, model_id, summary_snapshot, recognition_snapshot,
                 scene_tag, enrichment_intent, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                novel_id,
                enrichment_id,
                original_snapshot,
                rewrite_text,
                model_id,
                summary_snapshot,
                recognition_snapshot,
                scene_tag,
                enrichment_intent,
                status,
            ),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def list_suggestions_by_chapter(chapter_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM enrichment_suggestions
            WHERE chapter_id = ?
            ORDER BY applied_at DESC, id DESC
            """,
            (chapter_id,),
        )
        return _rows_to_dicts(await cur.fetchall())


async def get_suggestion(suggestion_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM enrichment_suggestions WHERE id = ?",
            (suggestion_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_latest_applied_suggestion(
    chapter_id: int,
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM enrichment_suggestions
            WHERE chapter_id = ? AND status = 'applied'
            ORDER BY applied_at DESC, id DESC
            LIMIT 1
            """,
            (chapter_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def mark_suggestion_status(
    suggestion_id: int, status: str
) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE enrichment_suggestions SET status = ? WHERE id = ?",
            (status, suggestion_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def touch_suggestion_applied(suggestion_id: int) -> bool:
    """把指定 suggestion 重新标记为 applied (用于回滚恢复)."""
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE enrichment_suggestions
            SET status = 'applied', applied_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (suggestion_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_suggestions_by_novel(novel_id: int) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM enrichment_suggestions WHERE novel_id = ?",
            (novel_id,),
        )
        await db.commit()
    return int(cur.rowcount or 0)


# ============================================================================
# AI 小说创作 (AI Creation) CRUD
# ============================================================================


def _decode_ai_json(raw: Any) -> Any:
    """AI 创作模块通用 JSON 解码 (initial_concepts / style_pref / kg_diff / critic_report)."""
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_ai_project(row: aiosqlite.Row) -> Dict[str, Any]:
    data = dict(row)
    data["initial_concepts"] = _decode_ai_json(data.get("initial_concepts")) or []
    data["style_pref"] = _decode_ai_json(data.get("style_pref")) or {}
    return data


def _row_to_ai_chapter(row: aiosqlite.Row) -> Dict[str, Any]:
    return dict(row)


def _row_to_ai_variant(row: aiosqlite.Row) -> Dict[str, Any]:
    data = dict(row)
    data["kg_diff"] = _decode_ai_json(data.get("kg_diff")) or {}
    data["critic_report"] = _decode_ai_json(data.get("critic_report")) or {}
    # P0-#3: 显式转换 superseded 为 bool/int, 方便前端判断
    data["superseded"] = int(data.get("superseded") or 0)
    data["generation_round"] = int(data.get("generation_round") or 1)
    return data


# --- ai_projects ----------------------------------------------------------


async def create_ai_project(
    *,
    title: str,
    genre: str = "",
    worldview: str = "",
    outline: str = "",
    initial_concepts: Optional[List[Dict[str, Any]]] = None,
    style_pref: Optional[Dict[str, Any]] = None,
    model_id: Optional[int] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_projects
                (title, genre, worldview, outline, initial_concepts,
                 style_pref, model_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                genre.strip(),
                worldview.strip(),
                outline.strip(),
                json.dumps(initial_concepts or [], ensure_ascii=False),
                json.dumps(style_pref or {}, ensure_ascii=False),
                model_id,
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def list_ai_projects() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_projects ORDER BY created_at DESC, id DESC"
        )
        return [_row_to_ai_project(r) for r in await cur.fetchall()]


async def get_ai_project(project_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_projects WHERE id = ?", (project_id,)
        )
        row = await cur.fetchone()
        return _row_to_ai_project(row) if row else None


async def update_ai_project(
    project_id: int,
    *,
    title: Optional[str] = None,
    genre: Optional[str] = None,
    worldview: Optional[str] = None,
    outline: Optional[str] = None,
    initial_concepts: Optional[List[Dict[str, Any]]] = None,
    style_pref: Optional[Dict[str, Any]] = None,
    model_id: Optional[int] = None,
    current_chapter_no: Optional[int] = None,
    status: Optional[str] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if title is not None:
        sets.append("title = ?")
        values.append(title.strip())
    if genre is not None:
        sets.append("genre = ?")
        values.append(genre.strip())
    if worldview is not None:
        sets.append("worldview = ?")
        values.append(worldview.strip())
    if outline is not None:
        sets.append("outline = ?")
        values.append(outline.strip())
    if initial_concepts is not None:
        sets.append("initial_concepts = ?")
        values.append(json.dumps(initial_concepts, ensure_ascii=False))
    if style_pref is not None:
        sets.append("style_pref = ?")
        values.append(json.dumps(style_pref, ensure_ascii=False))
    if model_id is not None:
        sets.append("model_id = ?")
        values.append(model_id)
    if current_chapter_no is not None:
        sets.append("current_chapter_no = ?")
        values.append(int(current_chapter_no))
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.append(project_id)
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_projects SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_project(project_id: int) -> bool:
    """级联删除 (依赖外键 ON DELETE CASCADE)."""
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute("DELETE FROM ai_projects WHERE id = ?", (project_id,))
        await db.commit()
    return cur.rowcount > 0


# --- ai_chapters ----------------------------------------------------------


async def create_ai_chapter(
    *,
    project_id: int,
    chapter_no: int,
    title: str = "",
    user_intent: str = "",
    status: str = "draft",
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_chapters
                (project_id, chapter_no, title, user_intent, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, chapter_no, title.strip(), user_intent.strip(), status),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def get_ai_chapter(chapter_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapters WHERE id = ?", (chapter_id,)
        )
        row = await cur.fetchone()
        return _row_to_ai_chapter(row) if row else None


async def list_ai_chapters(project_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapters WHERE project_id = ? ORDER BY chapter_no ASC",
            (project_id,),
        )
        return [_row_to_ai_chapter(r) for r in await cur.fetchall()]


async def update_ai_chapter(
    chapter_id: int,
    *,
    title: Optional[str] = None,
    user_intent: Optional[str] = None,
    status: Optional[str] = None,
    selected_variant_id: Optional[int] = None,
    final_content: Optional[str] = None,
    word_count: Optional[int] = None,
    kg_extracted: Optional[int] = None,
    confirmed_at: Optional[str] = None,
    chapter_no: Optional[int] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if title is not None:
        sets.append("title = ?")
        values.append(title.strip())
    if user_intent is not None:
        sets.append("user_intent = ?")
        values.append(user_intent.strip())
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if selected_variant_id is not None:
        sets.append("selected_variant_id = ?")
        values.append(int(selected_variant_id))
    if final_content is not None:
        sets.append("final_content = ?")
        values.append(final_content)
    if word_count is not None:
        sets.append("word_count = ?")
        values.append(int(word_count))
    if kg_extracted is not None:
        sets.append("kg_extracted = ?")
        values.append(int(kg_extracted))
    if confirmed_at is not None:
        sets.append("confirmed_at = ?")
        values.append(confirmed_at)
    if chapter_no is not None:
        sets.append("chapter_no = ?")
        values.append(int(chapter_no))
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.append(chapter_id)
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_chapters SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_chapter(chapter_id: int) -> bool:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "DELETE FROM ai_chapters WHERE id = ?", (chapter_id,)
        )
        await db.commit()
    return cur.rowcount > 0


# --- ai_chapter_variants --------------------------------------------------


async def insert_ai_variant(
    *,
    chapter_id: int,
    variant_index: int,
    planner_direction: str = "",
    content: str = "",
    focus_summary: str = "",
    kg_diff: Optional[Dict[str, Any]] = None,
    critic_report: Optional[Dict[str, Any]] = None,
    score: float = 0.0,
    model_id: Optional[int] = None,
    generation_round: int = 1,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_chapter_variants
                (chapter_id, variant_index, planner_direction, content,
                 focus_summary, kg_diff, critic_report, score, model_id,
                 generation_round)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                int(variant_index),
                planner_direction.strip(),
                content,
                focus_summary.strip(),
                json.dumps(kg_diff or {}, ensure_ascii=False),
                json.dumps(critic_report or {}, ensure_ascii=False),
                float(score),
                model_id,
                int(generation_round),
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def list_ai_variants(
    chapter_id: int, include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """列出变体. 默认只返回当前 round 的活跃变体; 历史版本需显式 include."""
    async with get_db() as db:
        if include_superseded:
            cur = await db.execute(
                "SELECT * FROM ai_chapter_variants WHERE chapter_id = ? "
                "ORDER BY generation_round DESC, variant_index ASC",
                (chapter_id,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM ai_chapter_variants WHERE chapter_id = ? "
                "AND superseded = 0 "
                "ORDER BY generation_round DESC, variant_index ASC",
                (chapter_id,),
            )
        return [_row_to_ai_variant(r) for r in await cur.fetchall()]


async def list_ai_variants_full_history(chapter_id: int) -> List[Dict[str, Any]]:
    """列出全部变体 (含历史), 按轮次/索引排序. 供 P0-#3 版本历史 UI 使用."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapter_variants WHERE chapter_id = ? "
            "ORDER BY generation_round DESC, variant_index ASC, created_at DESC",
            (chapter_id,),
        )
        return [_row_to_ai_variant(r) for r in await cur.fetchall()]


async def archive_ai_variants(chapter_id: int, round_no: int) -> int:
    """P0-#3: 重新生成时把当前轮次的所有变体标 superseded=1.
    返回被归档的变体数.
    """
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE ai_chapter_variants
            SET superseded = 1, superseded_at = CURRENT_TIMESTAMP
            WHERE chapter_id = ? AND generation_round = ? AND superseded = 0
            """,
            (chapter_id, round_no),
        )
        await db.commit()
    return int(cur.rowcount or 0)


async def max_variant_round(chapter_id: int) -> int:
    """返回该章节已生成的最大轮次. 用于 P0-#3 决定下一轮 round 编号."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT MAX(generation_round) AS r FROM ai_chapter_variants "
            "WHERE chapter_id = ?",
            (chapter_id,),
        )
        row = await cur.fetchone()
        if not row or row["r"] is None:
            return 0
        return int(row["r"])


async def get_ai_variant(variant_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapter_variants WHERE id = ?", (variant_id,)
        )
        row = await cur.fetchone()
        return _row_to_ai_variant(row) if row else None


async def update_ai_variant(
    variant_id: int,
    *,
    critic_report: Optional[Dict[str, Any]] = None,
    score: Optional[float] = None,
    kg_diff: Optional[Dict[str, Any]] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if critic_report is not None:
        sets.append("critic_report = ?")
        values.append(json.dumps(critic_report, ensure_ascii=False))
    if score is not None:
        sets.append("score = ?")
        values.append(float(score))
    if kg_diff is not None:
        sets.append("kg_diff = ?")
        values.append(json.dumps(kg_diff, ensure_ascii=False))
    if not sets:
        return False
    values.append(variant_id)
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_chapter_variants SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_variants_by_chapter(chapter_id: int) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM ai_chapter_variants WHERE chapter_id = ?",
            (chapter_id,),
        )
        await db.commit()
    return int(cur.rowcount or 0)


# --- AI 创作专用知识图谱 --------------------------------------------------


async def get_ai_knowledge_graph(project_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """返回项目级 KG (独立 5 表), 结构与现有 get_knowledge_graph 一致."""
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, project_id, entity_id, name, attributes,
                   source_chapter_id, model_id, extras, created_at, updated_at
            FROM ai_kg_characters WHERE project_id = ? ORDER BY entity_id
            """,
            (project_id,),
        )
        characters: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            characters.append(row)

        cur = await db.execute(
            """
            SELECT id, project_id, entity_id, name, attributes,
                   source_chapter_id, model_id, extras, created_at, updated_at
            FROM ai_kg_events WHERE project_id = ? ORDER BY entity_id
            """,
            (project_id,),
        )
        events: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            events.append(row)

        cur = await db.execute(
            """
            SELECT id, project_id, source_entity_id, target_entity_id,
                   relation, role, action, properties, extras, source_chapter_id
            FROM ai_kg_character_event_relations WHERE project_id = ?
            """,
            (project_id,),
        )
        ce_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            ce_relations.append(row)

        cur = await db.execute(
            """
            SELECT id, project_id, source_entity_id, target_entity_id,
                   relation, properties, extras, source_chapter_id
            FROM ai_kg_character_relations WHERE project_id = ?
            """,
            (project_id,),
        )
        cc_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            cc_relations.append(row)

        cur = await db.execute(
            """
            SELECT id, project_id, source_entity_id, target_entity_id,
                   relation, properties, extras, source_chapter_id
            FROM ai_kg_event_relations WHERE project_id = ?
            """,
            (project_id,),
        )
        ee_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            ee_relations.append(row)

        # ④ locations
        cur = await db.execute(
            """
            SELECT id, project_id, entity_id, name, location_type, attributes,
                   source_chapter_id, model_id, extras, created_at, updated_at
            FROM ai_kg_locations WHERE project_id = ? ORDER BY name
            """,
            (project_id,),
        )
        locations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            locations.append(row)

        # ⑤ plot_threads (open/hinting 优先)
        cur = await db.execute(
            """
            SELECT id, project_id, thread_id, title, thread_type, status, priority,
                   introduced_chapter_id, resolved_chapter_id, related_entity_ids,
                   notes, source_chapter_id, model_id, created_at, updated_at
            FROM ai_kg_plot_threads WHERE project_id = ?
            ORDER BY
                CASE status WHEN 'open' THEN 0 WHEN 'hinting' THEN 1
                            WHEN 'resolving' THEN 2 WHEN 'resolved' THEN 3
                            WHEN 'dropped' THEN 4 ELSE 5 END,
                priority DESC, created_at ASC
            """,
            (project_id,),
        )
        threads: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            if row.get("related_entity_ids"):
                try:
                    row["related_entity_ids"] = json.loads(row["related_entity_ids"])
                except (TypeError, ValueError):
                    row["related_entity_ids"] = []
            threads.append(row)

    return {
        "characters": characters,
        "events": events,
        "locations": locations,
        "plot_threads": threads,
        "character_event_relations": ce_relations,
        "character_relations": cc_relations,
        "event_relations": ee_relations,
    }


async def upsert_ai_kg_from_extraction(
    project_id: int,
    *,
    source_chapter_id: Optional[int],
    characters: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    character_event_relations: List[Dict[str, Any]],
    character_relations: List[Dict[str, Any]],
    event_relations: List[Dict[str, Any]],
    locations: Optional[List[Dict[str, Any]]] = None,
    model_id: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """根据单章节抽取结果, UPSERT 到项目级 KG (按 entity_id 同名合并属性).

    合并策略:
    - 已存在 (project_id, entity_id): 合并 attributes (后者覆盖前者), ⑥结构化字段用新值
    - 不存在: 插入新行
    - 关系表: 同 source/target/relation 三元组视为同一条, 重复则跳过
    - ④ Locations / ⑤ Threads / ⑩ character_appearances 走独立分支
    """
    stored: Dict[str, List[Dict[str, Any]]] = {
        "characters": [],
        "events": [],
        "locations": [],
        "character_event_relations": [],
        "character_relations": [],
        "event_relations": [],
    }

    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")

        # ---- characters ----
        for c in characters:
            entity_id = str(c.get("entity_id") or c.get("id") or "").strip()
            if not entity_id:
                continue
            cur = await db.execute(
                "SELECT id, attributes FROM ai_kg_characters "
                "WHERE project_id = ? AND entity_id = ?",
                (project_id, entity_id),
            )
            row = await cur.fetchone()
            merged_attrs = {**(c.get("attributes") or {})}
            extras = _build_entity_extras(c)
            # ⑥ 结构化字段: 来自实体本身, 优先于 attributes
            structured = {
                "role": c.get("role"),
                "faction": c.get("faction"),
                "current_location_entity_id": c.get("current_location_entity_id"),
                "status": c.get("status"),
                "first_appearance_chapter_id": c.get("first_appearance_chapter_id"),
                "importance": c.get("importance"),
            }
            structured = {k: v for k, v in structured.items() if v not in (None, "")}

            if row:
                old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
                merged_attrs = {**old_attrs, **merged_attrs}
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + ([source_chapter_id] if source_chapter_id else []))
                )
                # 动态 SET 子句: 只更新有值的新结构化字段
                set_clauses = [
                    "name = ?",
                    "attributes = ?",
                    "extras = ?",
                    "source_chapter_id = COALESCE(?, source_chapter_id)",
                    "updated_at = CURRENT_TIMESTAMP",
                ]
                params: List[Any] = [
                    str(c.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    _encode_extras(extras),
                    source_chapter_id,
                ]
                for k, v in structured.items():
                    set_clauses.append(f"{k} = ?")
                    params.append(v)
                params.append(row["id"])
                await db.execute(
                    f"UPDATE ai_kg_characters SET {', '.join(set_clauses)} WHERE id = ?",
                    params,
                )
                stored["characters"].append({
                    "id": row["id"], "project_id": project_id, "entity_id": entity_id,
                    "name": c.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    **structured,
                })
            else:
                if source_chapter_id:
                    extras["source_chapter_ids"] = [source_chapter_id]
                cols = ["project_id", "entity_id", "name", "attributes",
                        "source_chapter_id", "model_id", "extras"]
                vals: List[Any] = [
                    project_id, entity_id,
                    str(c.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    source_chapter_id, model_id,
                    _encode_extras(extras),
                ]
                for k, v in structured.items():
                    cols.append(k)
                    vals.append(v)
                placeholders = ", ".join(["?"] * len(vals))
                cur = await db.execute(
                    f"INSERT INTO ai_kg_characters ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )
                stored["characters"].append({
                    "id": cur.lastrowid, "project_id": project_id, "entity_id": entity_id,
                    "name": c.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    **structured,
                })

            # ⑩ 出场记录: 把该角色与本章的关联写入 ai_kg_character_appearances
            if source_chapter_id:
                try:
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO ai_kg_character_appearances
                            (project_id, entity_id, chapter_id, role, importance)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            project_id, entity_id, source_chapter_id,
                            str(c.get("role") or "出场")[:50],
                            int(c.get("importance") or 2) if isinstance(c.get("importance"), (int, float)) else 2,
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("character_appearances upsert skipped for %s", entity_id)

        # ---- events ----
        for e in events:
            entity_id = str(e.get("entity_id") or e.get("id") or "").strip()
            if not entity_id:
                continue
            cur = await db.execute(
                "SELECT id, attributes FROM ai_kg_events "
                "WHERE project_id = ? AND entity_id = ?",
                (project_id, entity_id),
            )
            row = await cur.fetchone()
            merged_attrs = {**(e.get("attributes") or {})}
            extras = _build_entity_extras(e)
            structured = {
                "in_story_time": e.get("in_story_time"),
                "chapter_time_label": e.get("chapter_time_label"),
                "importance": e.get("importance"),
            }
            structured = {k: v for k, v in structured.items() if v not in (None, "")}

            if row:
                old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
                merged_attrs = {**old_attrs, **merged_attrs}
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + ([source_chapter_id] if source_chapter_id else []))
                )
                set_clauses = [
                    "name = ?", "attributes = ?", "extras = ?",
                    "source_chapter_id = COALESCE(?, source_chapter_id)",
                    "updated_at = CURRENT_TIMESTAMP",
                ]
                params: List[Any] = [
                    str(e.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    _encode_extras(extras),
                    source_chapter_id,
                ]
                for k, v in structured.items():
                    set_clauses.append(f"{k} = ?")
                    params.append(v)
                params.append(row["id"])
                await db.execute(
                    f"UPDATE ai_kg_events SET {', '.join(set_clauses)} WHERE id = ?",
                    params,
                )
                stored["events"].append({
                    "id": row["id"], "project_id": project_id, "entity_id": entity_id,
                    "name": e.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    **structured,
                })
            else:
                if source_chapter_id:
                    extras["source_chapter_ids"] = [source_chapter_id]
                cols = ["project_id", "entity_id", "name", "attributes",
                        "source_chapter_id", "model_id", "extras"]
                vals: List[Any] = [
                    project_id, entity_id,
                    str(e.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    source_chapter_id, model_id,
                    _encode_extras(extras),
                ]
                for k, v in structured.items():
                    cols.append(k)
                    vals.append(v)
                placeholders = ", ".join(["?"] * len(vals))
                cur = await db.execute(
                    f"INSERT INTO ai_kg_events ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )
                stored["events"].append({
                    "id": cur.lastrowid, "project_id": project_id, "entity_id": entity_id,
                    "name": e.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    **structured,
                })

        # ---- ④ locations ----
        for loc in locations or []:
            entity_id = str(loc.get("entity_id") or loc.get("id") or "").strip()
            if not entity_id:
                continue
            cur = await db.execute(
                "SELECT id, attributes FROM ai_kg_locations "
                "WHERE project_id = ? AND entity_id = ?",
                (project_id, entity_id),
            )
            row = await cur.fetchone()
            merged_attrs = {**(loc.get("attributes") or {})}
            extras = _build_entity_extras(loc)
            if row:
                old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
                merged_attrs = {**old_attrs, **merged_attrs}
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + ([source_chapter_id] if source_chapter_id else []))
                )
                set_clauses = [
                    "name = ?", "attributes = ?", "extras = ?",
                    "source_chapter_id = COALESCE(?, source_chapter_id)",
                    "updated_at = CURRENT_TIMESTAMP",
                ]
                params: List[Any] = [
                    str(loc.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    _encode_extras(extras),
                    source_chapter_id,
                ]
                if loc.get("location_type"):
                    set_clauses.append("location_type = ?")
                    params.append(str(loc["location_type"])[:50])
                params.append(row["id"])
                await db.execute(
                    f"UPDATE ai_kg_locations SET {', '.join(set_clauses)} WHERE id = ?",
                    params,
                )
                stored["locations"].append({
                    "id": row["id"], "project_id": project_id, "entity_id": entity_id,
                    "name": loc.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    "location_type": loc.get("location_type"),
                })
            else:
                if source_chapter_id:
                    extras["source_chapter_ids"] = [source_chapter_id]
                cur = await db.execute(
                    """
                    INSERT INTO ai_kg_locations
                        (project_id, entity_id, name, location_type, attributes,
                         source_chapter_id, model_id, extras)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, entity_id,
                        str(loc.get("name", "")).strip()[:200] or entity_id,
                        str(loc.get("location_type") or "")[:50] or None,
                        _encode_attributes(merged_attrs),
                        source_chapter_id, model_id,
                        _encode_extras(extras),
                    ),
                )
                stored["locations"].append({
                    "id": cur.lastrowid, "project_id": project_id, "entity_id": entity_id,
                    "name": loc.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    "location_type": loc.get("location_type"),
                })

        # ---- relations: 去重插入 ----
        async def _insert_rel(
            table: str, source: str, target: str,
            relation: str, extras_payload: Dict[str, Any], **extra
        ) -> Optional[Dict[str, Any]]:
            cur = await db.execute(
                f"SELECT id FROM {table} WHERE project_id = ? "
                f"AND source_entity_id = ? AND target_entity_id = ? AND relation = ?",
                (project_id, source, target, relation),
            )
            if await cur.fetchone():
                return None
            extras = _build_relation_extras(extras_payload)
            if source_chapter_id:
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + [source_chapter_id])
                )
            cols = ["project_id", "source_entity_id", "target_entity_id",
                    "relation", "source_chapter_id", "extras"]
            vals: List[Any] = [project_id, source, target, relation,
                               source_chapter_id, _encode_extras(extras)]
            # ⑥ 关系结构化字段: relation_type
            rtype = extras_payload.get("relation_type")
            if rtype:
                cols.append("relation_type")
                vals.append(str(rtype)[:50])
            for k, v in extra.items():
                if k in cols:
                    continue
                cols.append(k)
                vals.append(v)
            placeholders = ", ".join(["?"] * len(vals))
            cur = await db.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                vals,
            )
            return {
                "id": cur.lastrowid, "project_id": project_id,
                "source_entity_id": source, "target_entity_id": target,
                "relation": relation, **extra, "source_chapter_id": source_chapter_id,
                "extras": extras,
            }

        for r in character_event_relations:
            src = str(r.get("source") or r.get("source_entity_id") or "").strip()
            tgt = str(r.get("target") or r.get("target_entity_id") or "").strip()
            if not src or not tgt:
                continue
            stored_row = await _insert_rel(
                "ai_kg_character_event_relations", src, tgt,
                str(r.get("relation") or "PARTICIPATES_IN").strip() or "PARTICIPATES_IN",
                r,
                role=r.get("role") or None,
                action=r.get("action") or None,
                properties=_encode_attributes(
                    r.get("properties") if isinstance(r.get("properties"), dict) else {}
                ),
            )
            if stored_row:
                stored_row["properties"] = r.get("properties") or {}
                stored["character_event_relations"].append(stored_row)

        for r in character_relations:
            src = str(r.get("source") or r.get("source_entity_id") or "").strip()
            tgt = str(r.get("target") or r.get("target_entity_id") or "").strip()
            if not src or not tgt:
                continue
            stored_row = await _insert_rel(
                "ai_kg_character_relations", src, tgt,
                str(r.get("relation") or "").strip() or "关联",
                r,
                properties=_encode_attributes(
                    r.get("properties") if isinstance(r.get("properties"), dict) else {}
                ),
            )
            if stored_row:
                stored_row["properties"] = r.get("properties") or {}
                stored["character_relations"].append(stored_row)

        for r in event_relations:
            src = str(r.get("source") or r.get("source_entity_id") or "").strip()
            tgt = str(r.get("target") or r.get("target_entity_id") or "").strip()
            if not src or not tgt:
                continue
            stored_row = await _insert_rel(
                "ai_kg_event_relations", src, tgt,
                str(r.get("relation") or "").strip() or "关联",
                r,
                properties=_encode_attributes(
                    r.get("properties") if isinstance(r.get("properties"), dict) else {}
                ),
            )
            if stored_row:
                stored_row["properties"] = r.get("properties") or {}
                stored["event_relations"].append(stored_row)

        await db.commit()
    return stored


async def upsert_ai_kg_plot_threads(
    project_id: int,
    *,
    source_chapter_id: Optional[int],
    threads: List[Dict[str, Any]],
    model_id: Optional[int] = None,
) -> Dict[str, int]:
    """⑤ plot_threads 批量 upsert. action=create|update|resolve|drop."""
    counts = {"create": 0, "update": 0, "resolve": 0, "drop": 0, "skip": 0}
    if not threads:
        return counts
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for t in threads:
            thread_id = str(t.get("thread_id") or "").strip()
            action = str(t.get("action") or "create").strip()
            title = str(t.get("title") or "").strip()
            if not thread_id or not title:
                counts["skip"] += 1
                continue
            cur = await db.execute(
                "SELECT id, status, priority, thread_type, related_entity_ids, notes "
                "FROM ai_kg_plot_threads WHERE project_id = ? AND thread_id = ?",
                (project_id, thread_id),
            )
            row = await cur.fetchone()
            status = str(t.get("status") or "open").strip()
            if action == "drop":
                if row:
                    await db.execute(
                        "DELETE FROM ai_kg_plot_threads WHERE id = ?", (row["id"],)
                    )
                    counts["drop"] += 1
                else:
                    counts["skip"] += 1
                continue
            if action == "resolve" and row:
                await db.execute(
                    """
                    UPDATE ai_kg_plot_threads
                    SET status = 'resolved',
                        resolved_chapter_id = COALESCE(?, resolved_chapter_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (source_chapter_id, row["id"]),
                )
                counts["resolve"] += 1
                continue
            priority = t.get("priority")
            try:
                priority_v = max(1, min(5, int(priority))) if priority not in (None, "") else 3
            except (TypeError, ValueError):
                priority_v = 3
            related = t.get("related_entity_ids") or []
            if isinstance(related, str):
                try:
                    related = json.loads(related)
                except (TypeError, ValueError):
                    related = []
            related_str = json.dumps(related, ensure_ascii=False) if related else None
            notes = str(t.get("notes") or "")[:1000] or None
            ttype = str(t.get("thread_type") or "")[:50] or None
            if row:
                # update
                await db.execute(
                    """
                    UPDATE ai_kg_plot_threads
                    SET title = ?, status = ?, priority = ?, thread_type = COALESCE(?, thread_type),
                        related_entity_ids = COALESCE(?, related_entity_ids),
                        notes = COALESCE(?, notes),
                        source_chapter_id = COALESCE(?, source_chapter_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (title, status, priority_v, ttype, related_str, notes, source_chapter_id, row["id"]),
                )
                counts["update"] += 1
            else:
                # create
                await db.execute(
                    """
                    INSERT INTO ai_kg_plot_threads
                        (project_id, thread_id, title, thread_type, status, priority,
                         introduced_chapter_id, related_entity_ids, notes,
                         source_chapter_id, model_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, thread_id, title, ttype, status, priority_v,
                        source_chapter_id, related_str, notes,
                        source_chapter_id, model_id,
                    ),
                )
                counts["create"] += 1
        await db.commit()
    return counts


async def list_ai_kg_plot_threads(
    project_id: int,
    *,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    threads: List[Dict[str, Any]] = []
    async with get_db() as db:
        sql = """
            SELECT id, project_id, thread_id, title, thread_type, status, priority,
                   introduced_chapter_id, resolved_chapter_id, related_entity_ids,
                   notes, source_chapter_id, model_id, created_at, updated_at
            FROM ai_kg_plot_threads
            WHERE project_id = ?
        """
        params: List[Any] = [project_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY priority DESC, created_at ASC"
        cur = await db.execute(sql, tuple(params))
        rows = await cur.fetchall()
    for r in rows:
        row = dict(r)
        if row.get("related_entity_ids"):
            try:
                row["related_entity_ids"] = json.loads(row["related_entity_ids"])
            except (TypeError, ValueError):
                row["related_entity_ids"] = []
        threads.append(row)
    return threads


# P1-#6: PlotThread 单条 CRUD
async def insert_ai_kg_plot_thread(
    project_id: int,
    *,
    thread_id: str,
    title: str,
    thread_type: str = "",
    status: str = "open",
    priority: int = 3,
    introduced_chapter_id: Optional[int] = None,
    resolved_chapter_id: Optional[int] = None,
    related_entity_ids: Optional[List[str]] = None,
    notes: str = "",
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_kg_plot_threads
                (project_id, thread_id, title, thread_type, status, priority,
                 introduced_chapter_id, resolved_chapter_id, related_entity_ids, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                thread_id,
                title.strip(),
                (thread_type or "").strip() or None,
                status,
                int(priority),
                introduced_chapter_id,
                resolved_chapter_id,
                json.dumps(related_entity_ids or [], ensure_ascii=False),
                notes or "",
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def update_ai_kg_plot_thread(
    project_id: int,
    thread_id: str,
    *,
    title: Optional[str] = None,
    thread_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    notes: Optional[str] = None,
    related_entity_ids: Optional[List[str]] = None,
    resolved_chapter_id: Optional[int] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if title is not None:
        sets.append("title = ?")
        values.append(title.strip())
    if thread_type is not None:
        sets.append("thread_type = ?")
        values.append((thread_type or "").strip() or None)
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if priority is not None:
        sets.append("priority = ?")
        values.append(int(priority))
    if notes is not None:
        sets.append("notes = ?")
        values.append(notes)
    if related_entity_ids is not None:
        sets.append("related_entity_ids = ?")
        values.append(json.dumps(related_entity_ids, ensure_ascii=False))
    if resolved_chapter_id is not None:
        sets.append("resolved_chapter_id = ?")
        values.append(int(resolved_chapter_id))
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([project_id, thread_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_kg_plot_threads SET {', '.join(sets)} "
            "WHERE project_id = ? AND thread_id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_kg_plot_thread(project_id: int, thread_id: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM ai_kg_plot_threads WHERE project_id = ? AND thread_id = ?",
            (project_id, thread_id),
        )
        await db.commit()
    return cur.rowcount > 0


async def list_ai_kg_locations(project_id: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, project_id, entity_id, name, location_type, attributes,
                   source_chapter_id, model_id, extras, created_at, updated_at
            FROM ai_kg_locations WHERE project_id = ?
            ORDER BY name
            """,
            (project_id,),
        )
        rows = await cur.fetchall()
    for r in rows:
        row = dict(r)
        row["attributes"] = _decode_attributes(row.get("attributes"))
        row["extras"] = _decode_extras(row.get("extras"))
        out.append(row)
    return out


async def list_ai_kg_character_appearances(
    project_id: int,
    *,
    entity_id: Optional[str] = None,
    chapter_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    where = ["project_id = ?"]
    params: List[Any] = [project_id]
    if entity_id:
        where.append("entity_id = ?")
        params.append(entity_id)
    if chapter_id:
        where.append("chapter_id = ?")
        params.append(chapter_id)
    async with get_db() as db:
        cur = await db.execute(
            f"""
            SELECT id, project_id, entity_id, chapter_id, role, importance, created_at
            FROM ai_kg_character_appearances
            WHERE {' AND '.join(where)}
            ORDER BY chapter_id ASC
            """,
            tuple(params),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_ai_chapter_kg_extraction(
    variant_id: int,
    *,
    entity_count: int,
    event_count: int,
) -> None:
    """① 抽取后更新变体的 kg_extracted_at + 计数."""
    async with get_db() as db:
        await db.execute(
            """
            UPDATE ai_chapter_variants
            SET kg_extracted_at = CURRENT_TIMESTAMP,
                kg_entity_count = ?,
                kg_event_count = ?
            WHERE id = ?
            """,
            (int(entity_count), int(event_count), int(variant_id)),
        )
        await db.commit()


async def update_ai_chapter_compass(
    chapter_id: int,
    *,
    score: Optional[float] = None,
    warnings: Optional[List[Dict[str, str]]] = None,
    summary: Optional[str] = None,
) -> None:
    """⑦ CompassAgent 评分入档."""
    sets: List[str] = []
    params: List[Any] = []
    if score is not None:
        sets.append("compass_score = ?")
        params.append(float(score))
    if warnings is not None:
        sets.append("compass_warnings = ?")
        params.append(json.dumps(warnings, ensure_ascii=False))
    if summary is not None:
        sets.append("compass_summary = ?")
        params.append(str(summary)[:2000])
    if not sets:
        return
    params.append(int(chapter_id))
    async with get_db() as db:
        await db.execute(
            f"UPDATE ai_chapters SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        await db.commit()


async def update_ai_project_themes(
    project_id: int,
    themes: List[Dict[str, Any]],
) -> None:
    """⑨ 更新项目级主题进度. themes = [{theme, progress(0-1), stage}, ...]"""
    async with get_db() as db:
        await db.execute(
            "UPDATE ai_projects SET themes_progress = ? WHERE id = ?",
            (json.dumps(themes, ensure_ascii=False), int(project_id)),
        )
        await db.commit()


async def get_ai_project_themes(project_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT themes_progress FROM ai_projects WHERE id = ?",
            (project_id,),
        )
        row = await cur.fetchone()
    if not row or not row["themes_progress"]:
        return []
    try:
        return json.loads(row["themes_progress"])
    except (TypeError, ValueError):
        return []


async def reconcile_kg_conflicts(
    project_id: int,
    *,
    chapter_id: int,
    conflicts: List[Dict[str, Any]],
) -> int:
    """② Critic 报告的 kg_conflicts 写回对应实体的 attributes.conflicts_observed.

    conflicts = [{entity, entity_type, claim, kg_fact, severity, chapter_no}, ...]
    返回写入的冲突数.
    """
    if not conflicts:
        return 0
    written = 0
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for c in conflicts:
            entity = (c.get("entity") or "").strip()
            entity_type = (c.get("entity_type") or "character").strip() or "character"
            if not entity:
                continue
            table = "ai_kg_characters" if entity_type == "character" else "ai_kg_events"
            cur = await db.execute(
                f"SELECT id, attributes, name FROM {table} "
                f"WHERE project_id = ? AND name = ? ORDER BY id LIMIT 1",
                (project_id, entity),
            )
            row = await cur.fetchone()
            if not row:
                continue
            old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
            arr = old_attrs.get("conflicts_observed") or []
            if not isinstance(arr, list):
                arr = []
            arr.append({
                "chapter_no": c.get("chapter_no") or chapter_id,
                "chapter_id": chapter_id,
                "quote": str(c.get("quote") or c.get("claim") or "")[:200],
                "kg_fact": str(c.get("kg_fact") or "")[:200],
                "severity": str(c.get("severity") or "warn"),
                "resolved": False,
            })
            old_attrs["conflicts_observed"] = arr
            await db.execute(
                f"UPDATE {table} SET attributes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (_encode_attributes(old_attrs), row["id"]),
            )
            written += 1
        await db.commit()
    return written


async def delete_ai_knowledge_graph(project_id: int) -> Dict[str, int]:
    """原子清空项目级 KG."""
    counts: Dict[str, int] = {}
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for table in (
            "ai_kg_character_appearances",
            "ai_kg_plot_threads",
            "ai_kg_locations",
            "ai_kg_character_event_relations",
            "ai_kg_character_relations",
            "ai_kg_event_relations",
            "ai_kg_events",
            "ai_kg_characters",
        ):
            cur = await db.execute(
                f"DELETE FROM {table} WHERE project_id = ?", (project_id,)
            )
            counts[table] = cur.rowcount or 0
        await db.commit()
    return counts


async def get_ai_kg_stats(project_id: int) -> Dict[str, int]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_characters WHERE project_id = ?",
            (project_id,),
        )
        char_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_events WHERE project_id = ?",
            (project_id,),
        )
        evt_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_locations WHERE project_id = ?",
            (project_id,),
        )
        loc_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_plot_threads "
            "WHERE project_id = ? AND status IN ('open', 'hinting', 'resolving')",
            (project_id,),
        )
        thread_open = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_character_relations WHERE project_id = ?",
            (project_id,),
        )
        cc_count = (await cur.fetchone())[0]
    return {
        "characters": char_count,
        "events": evt_count,
        "locations": loc_count,
        "threads_open": thread_open,
        "character_relations": cc_count,
    }


# ---------------------------------------------------------------------------
# KG 节点 / 关系 CRUD (供前端手动编辑图谱)
# ---------------------------------------------------------------------------
# 设计原则:
# - 走项目级 5 表 (ai_kg_characters / events / locations / *_relations),
#   与 LLM 抽取共用同一张表, 无须做视图同步.
# - 提供 insert / update / delete 三类原子操作; service 层负责校验.
# - 删除节点时级联清理引用该节点的关系, 避免悬挂引用.


async def get_ai_kg_character_by_entity(
    project_id: int, entity_id: str
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_kg_characters WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        row = await cur.fetchone()
    return _decode_kg_character_row(row) if row else None


async def get_ai_kg_event_by_entity(
    project_id: int, entity_id: str
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_kg_events WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        row = await cur.fetchone()
    return _decode_kg_event_row(row) if row else None


async def get_ai_kg_location_by_entity(
    project_id: int, entity_id: str
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_kg_locations WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        row = await cur.fetchone()
    return _decode_kg_location_row(row) if row else None


def _decode_kg_character_row(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["attributes"] = _decode_attributes(d.get("attributes"))
    d["extras"] = _decode_extras(d.get("extras"))
    return d


def _decode_kg_event_row(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["attributes"] = _decode_attributes(d.get("attributes"))
    d["extras"] = _decode_extras(d.get("extras"))
    return d


def _decode_kg_location_row(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["attributes"] = _decode_attributes(d.get("attributes"))
    d["extras"] = _decode_extras(d.get("extras"))
    return d


async def insert_ai_kg_character(
    project_id: int,
    *,
    entity_id: str,
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    role: Optional[str] = None,
    faction: Optional[str] = None,
    status: Optional[str] = None,
    importance: Optional[int] = None,
) -> int:
    """新增人物. entity_id 在项目内必须唯一, 冲突抛 ValueError."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM ai_kg_characters WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        if await cur.fetchone():
            raise ValueError(f"人物 entity_id={entity_id} 已存在")
        cur = await db.execute(
            """
            INSERT INTO ai_kg_characters
              (project_id, entity_id, name, attributes, role, faction, status, importance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, entity_id, name,
                _encode_attributes(attributes or {}),
                role, faction, status, importance,
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def update_ai_kg_character(
    project_id: int,
    entity_id: str,
    *,
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
    role: Optional[str] = None,
    faction: Optional[str] = None,
    status: Optional[str] = None,
    importance: Optional[int] = None,
) -> bool:
    """按 entity_id 更新人物字段. None 表示不动."""
    sets: List[str] = []
    values: List[Any] = []
    if name is not None:
        sets.append("name = ?")
        values.append(name.strip()[:200])
    if attributes is not None:
        sets.append("attributes = ?")
        values.append(_encode_attributes(attributes))
    if role is not None:
        sets.append("role = ?")
        values.append(role or None)
    if faction is not None:
        sets.append("faction = ?")
        values.append(faction or None)
    if status is not None:
        sets.append("status = ?")
        values.append(status or None)
    if importance is not None:
        sets.append("importance = ?")
        values.append(int(importance) if importance else None)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([project_id, entity_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_kg_characters SET {', '.join(sets)} "
            "WHERE project_id = ? AND entity_id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_kg_character(
    project_id: int, entity_id: str
) -> bool:
    """删除人物, 级联清理引用该 entity_id 的关系."""
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "DELETE FROM ai_kg_character_event_relations "
            "WHERE project_id = ? AND (source_entity_id = ? OR target_entity_id = ?)",
            (project_id, entity_id, entity_id),
        )
        await db.execute(
            "DELETE FROM ai_kg_character_relations "
            "WHERE project_id = ? AND (source_entity_id = ? OR target_entity_id = ?)",
            (project_id, entity_id, entity_id),
        )
        await db.execute(
            "DELETE FROM ai_kg_character_appearances "
            "WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        cur = await db.execute(
            "DELETE FROM ai_kg_characters WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        await db.commit()
    return cur.rowcount > 0


async def insert_ai_kg_event(
    project_id: int,
    *,
    entity_id: str,
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    importance: Optional[int] = None,
    in_story_time: Optional[str] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM ai_kg_events WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        if await cur.fetchone():
            raise ValueError(f"事件 entity_id={entity_id} 已存在")
        cur = await db.execute(
            """
            INSERT INTO ai_kg_events
              (project_id, entity_id, name, attributes, importance, in_story_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, entity_id, name,
                _encode_attributes(attributes or {}),
                importance, in_story_time,
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def update_ai_kg_event(
    project_id: int,
    entity_id: str,
    *,
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
    importance: Optional[int] = None,
    in_story_time: Optional[str] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if name is not None:
        sets.append("name = ?"); values.append(name.strip()[:200])
    if attributes is not None:
        sets.append("attributes = ?"); values.append(_encode_attributes(attributes))
    if importance is not None:
        sets.append("importance = ?"); values.append(int(importance) if importance else None)
    if in_story_time is not None:
        sets.append("in_story_time = ?"); values.append(in_story_time or None)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([project_id, entity_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_kg_events SET {', '.join(sets)} "
            "WHERE project_id = ? AND entity_id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_kg_event(project_id: int, entity_id: str) -> bool:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "DELETE FROM ai_kg_character_event_relations "
            "WHERE project_id = ? AND target_entity_id = ?",
            (project_id, entity_id),
        )
        await db.execute(
            "DELETE FROM ai_kg_event_relations "
            "WHERE project_id = ? AND (source_entity_id = ? OR target_entity_id = ?)",
            (project_id, entity_id, entity_id),
        )
        cur = await db.execute(
            "DELETE FROM ai_kg_events WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        await db.commit()
    return cur.rowcount > 0


async def insert_ai_kg_location(
    project_id: int,
    *,
    entity_id: str,
    name: str,
    location_type: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM ai_kg_locations WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        if await cur.fetchone():
            raise ValueError(f"地点 entity_id={entity_id} 已存在")
        cur = await db.execute(
            """
            INSERT INTO ai_kg_locations
              (project_id, entity_id, name, location_type, attributes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_id, entity_id, name, location_type,
                _encode_attributes(attributes or {}),
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def update_ai_kg_location(
    project_id: int,
    entity_id: str,
    *,
    name: Optional[str] = None,
    location_type: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if name is not None:
        sets.append("name = ?"); values.append(name.strip()[:200])
    if location_type is not None:
        sets.append("location_type = ?"); values.append(location_type or None)
    if attributes is not None:
        sets.append("attributes = ?"); values.append(_encode_attributes(attributes))
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([project_id, entity_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_kg_locations SET {', '.join(sets)} "
            "WHERE project_id = ? AND entity_id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_kg_location(project_id: int, entity_id: str) -> bool:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        # 同步把人物.current_location_entity_id 指向该 entity 的引用清空
        await db.execute(
            "UPDATE ai_kg_characters SET current_location_entity_id = NULL "
            "WHERE project_id = ? AND current_location_entity_id = ?",
            (project_id, entity_id),
        )
        cur = await db.execute(
            "DELETE FROM ai_kg_locations WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        await db.commit()
    return cur.rowcount > 0


async def insert_ai_kg_character_event_relation(
    project_id: int,
    *,
    source_entity_id: str,
    target_entity_id: str,
    relation: str = "PARTICIPATES_IN",
    role: Optional[str] = None,
    action: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_kg_character_event_relations
              (project_id, source_entity_id, target_entity_id,
               relation, role, action, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, source_entity_id, target_entity_id,
                relation, role, action,
                _encode_attributes(properties or {}),
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def delete_ai_kg_relation(
    project_id: int,
    rel_kind: str,
    rel_id: int,
) -> bool:
    """rel_kind ∈ {'ce', 'cc', 'ee'} 对应 character_event / character / event 关系表."""
    table_map = {
        "ce": "ai_kg_character_event_relations",
        "cc": "ai_kg_character_relations",
        "ee": "ai_kg_event_relations",
    }
    table = table_map.get(rel_kind)
    if not table:
        raise ValueError(f"未知的 rel_kind: {rel_kind}")
    async with get_db() as db:
        cur = await db.execute(
            f"DELETE FROM {table} WHERE id = ? AND project_id = ?",
            (rel_id, project_id),
        )
        await db.commit()
    return cur.rowcount > 0


