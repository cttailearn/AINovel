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

