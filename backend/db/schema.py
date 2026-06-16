from __future__ import annotations

from typing import List

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
        kg_extracted_at TIMESTAMP,
        kg_entity_count INTEGER NOT NULL DEFAULT 0,
        kg_event_count INTEGER NOT NULL DEFAULT 0,
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
        UNIQUE (chapter_id, generation_round, variant_index)
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
