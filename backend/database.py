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
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE,
        FOREIGN KEY (source_chapter_id) REFERENCES ai_chapters(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_kg_ee_rels_project ON ai_kg_event_relations(project_id)",
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

    return {
        "characters": characters,
        "events": events,
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
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_chapter_variants
                (chapter_id, variant_index, planner_direction, content,
                 focus_summary, kg_diff, critic_report, score, model_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def list_ai_variants(chapter_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapter_variants WHERE chapter_id = ? "
            "ORDER BY variant_index ASC",
            (chapter_id,),
        )
        return [_row_to_ai_variant(r) for r in await cur.fetchall()]


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

    return {
        "characters": characters,
        "events": events,
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
    model_id: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """根据单章节抽取结果, UPSERT 到项目级 KG (按 entity_id 同名合并属性).

    合并策略:
    - 已存在 (project_id, entity_id): 合并 attributes (后者覆盖前者), extras 替换, source_chapter_id 追加到 extras
    - 不存在: 插入新行
    - 关系表: 同 source/target/relation 三元组视为同一条, 重复则跳过
    """
    stored: Dict[str, List[Dict[str, Any]]] = {
        "characters": [],
        "events": [],
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
            if row:
                old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
                merged_attrs = {**old_attrs, **merged_attrs}
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + ([source_chapter_id] if source_chapter_id else []))
                )
                await db.execute(
                    """
                    UPDATE ai_kg_characters
                    SET name = ?, attributes = ?, extras = ?,
                        source_chapter_id = COALESCE(?, source_chapter_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        str(c.get("name", "")).strip()[:200] or entity_id,
                        _encode_attributes(merged_attrs),
                        _encode_extras(extras),
                        source_chapter_id,
                        row["id"],
                    ),
                )
                stored["characters"].append({
                    "id": row["id"], "project_id": project_id, "entity_id": entity_id,
                    "name": c.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                })
            else:
                if source_chapter_id:
                    extras["source_chapter_ids"] = [source_chapter_id]
                cur = await db.execute(
                    """
                    INSERT INTO ai_kg_characters
                        (project_id, entity_id, name, attributes,
                         source_chapter_id, model_id, extras)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, entity_id,
                        str(c.get("name", "")).strip()[:200] or entity_id,
                        _encode_attributes(merged_attrs),
                        source_chapter_id, model_id,
                        _encode_extras(extras),
                    ),
                )
                stored["characters"].append({
                    "id": cur.lastrowid, "project_id": project_id, "entity_id": entity_id,
                    "name": c.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                })

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
            if row:
                old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
                merged_attrs = {**old_attrs, **merged_attrs}
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + ([source_chapter_id] if source_chapter_id else []))
                )
                await db.execute(
                    """
                    UPDATE ai_kg_events
                    SET name = ?, attributes = ?, extras = ?,
                        source_chapter_id = COALESCE(?, source_chapter_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        str(e.get("name", "")).strip()[:200] or entity_id,
                        _encode_attributes(merged_attrs),
                        _encode_extras(extras),
                        source_chapter_id,
                        row["id"],
                    ),
                )
                stored["events"].append({
                    "id": row["id"], "project_id": project_id, "entity_id": entity_id,
                    "name": e.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                })
            else:
                if source_chapter_id:
                    extras["source_chapter_ids"] = [source_chapter_id]
                cur = await db.execute(
                    """
                    INSERT INTO ai_kg_events
                        (project_id, entity_id, name, attributes,
                         source_chapter_id, model_id, extras)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, entity_id,
                        str(e.get("name", "")).strip()[:200] or entity_id,
                        _encode_attributes(merged_attrs),
                        source_chapter_id, model_id,
                        _encode_extras(extras),
                    ),
                )
                stored["events"].append({
                    "id": cur.lastrowid, "project_id": project_id, "entity_id": entity_id,
                    "name": e.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
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
            for k, v in extra.items():
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


async def delete_ai_knowledge_graph(project_id: int) -> Dict[str, int]:
    """原子清空项目级 KG."""
    counts: Dict[str, int] = {}
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for table in (
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
            "SELECT COUNT(*) FROM ai_kg_character_event_relations WHERE project_id = ?",
            (project_id,),
        )
        ce_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_character_relations WHERE project_id = ?",
            (project_id,),
        )
        cc_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_event_relations WHERE project_id = ?",
            (project_id,),
        )
        ee_count = (await cur.fetchone())[0]
    return {
        "characters": char_count, "events": evt_count,
        "participations": ce_count, "character_relations": cc_count,
        "event_relations": ee_count,
    }


