# AI 小说创作 · 知识图谱架构分析与优化方案

> 目的: 让知识图谱真正成为"创作者的护栏", 而不只是事后抽取的"字典", 帮用户不偏离大纲/不破设定/不丢伏笔.

---

## 1. 当前架构盘点

### 1.1 表结构 (5 张实体/关系表)

| 表 | 角色 | 关键字段 | 当前问题 |
|---|---|---|---|
| `ai_chapters` | 章节 | title, status, selected_variant_id, final_content, word_count, kg_extracted | 标题可空; kg_extracted 只是 0/1 标记, 无追溯 |
| `ai_chapter_variants` | 候选版本 | variant_index, planner_direction, content, focus_summary, kg_diff, critic_report, score | kg_diff 没被消费; score 仅供参考 |
| `ai_kg_characters` | 人物 | entity_id, name, attributes (JSON), source_chapter_id, model_id, extras | attributes 是黑盒 JSON, 无法高效查询; 不知道"哪几章出场" |
| `ai_kg_events` | 事件 | entity_id, name, attributes, source_chapter_id | 同上; 缺时间戳; 不知道"承接了哪个伏笔" |
| `ai_kg_character_event_relations` | 人物↔事件 | source/target entity_id, relation (PARTICIPATES_IN), role, action, properties | 只有一种 relation (PARTICIPATES_IN), 太弱 |
| `ai_kg_character_relations` | 人物↔人物 | source/target entity_id, relation, properties | 没有"时间窗口" (什么时候开始/结束) |
| `ai_kg_event_relations` | 事件↔事件 | source/target entity_id, relation, properties | 没法区分"因→果"和"并置" |

### 1.2 流水线

```
Planner(3 方向) → 3×Writer 并行(每章 2500-3500 字) → 3×Critic 并行(5 维打分)
                                          ↓
                          EntityExtractor(只在 confirm_chapter 时跑一次)
                                          ↓
                          ai_kg_* upsert (按 entity_id 合并, 取最新 attributes)
```

### 1.3 当前已在用、且解决了部分问题

- ✅ 项目级 KG 与小说级 KG **物理隔离** (ai_kg_* vs novels 下的 KG)
- ✅ Project 设定作为"根设定"塞入每段 prompt
- ✅ 抽出时按 `(project_id, entity_id)` 合并
- ✅ Critic 报告了 `kg_conflicts` 字段 (但**没人用它**)

---

## 2. 当前痛点 (按"防偏离"重要性排序)

| # | 痛点 | 后果 | 优先级 |
|---|---|---|---|
| **P0** | **KG 不带时间轴**, 不知道事件发生顺序, 也不知道"第几章发生过" | 时间线混乱, 角色忽然出现在不该出现的地方 | 🔴 极高 |
| **P0** | **没有 PlotThread 实体**, "伏笔"在 Planner 提示词里是字符串, 抽不到 KG | 30 章后伏笔忘光, 读者看到的是"烂尾" | 🔴 极高 |
| **P0** | **attributes 是 JSON 文本**, 无法做"年龄/位置/关系"等结构化查询 | Writer 偷改属性没人发现 | 🔴 极高 |
| **P1** | **没有 Location 实体**, 角色"住在哪"不知道, 跨场景冲突无解 | 角色瞬间移动, 违反世界观 | 🟠 高 |
| **P1** | **抽取只在 confirm_chapter 时跑一次**, 中间保存的版本不入库 | 写到一半被切换, 之前的实体丢失 | 🟠 高 |
| **P1** | **没有 Importance 字段**, 主角和路人权重一样 | 上下文里塞一堆"张三"喧宾夺主 | 🟠 高 |
| **P1** | **kg_diff 字段无人使用** (在 variants 表里) | 重复生成不知道改了啥 | 🟠 高 |
| **P2** | **冲突报告 (kg_conflicts) 仅作参考**, 不阻塞生成 | 设定被打破直接被接受 | 🟡 中 |
| **P2** | **没有"创作期"维度** (act/phase), Planner 不知道当前在铺垫/冲突/高潮 | 节奏失衡 | 🟡 中 |
| **P2** | **没有 Theme 实体**, 主题只能靠 prompt 暗示 | 故事核心立意松散 | 🟡 中 |
| **P2** | **抽取用的是 LLM, 没有 schema 校验**, JSON 解析失败直接丢弃 | 关键实体没进 KG | 🟡 中 |
| **P3** | **没有跨项目复用**, 用户开新书要重头再来 | 重度用户不便 | ⚪ 低 |
| **P3** | **没有 KG 检索 (RAG) 排序**, 全量塞给 LLM 浪费 token | 上下文越来越长, 成本和噪声 | ⚪ 低 |

---

## 3. 优化方案: 3 个阶段

> 设计原则: **不破现有数据** (向后兼容), **不堆表** (能加字段就加字段, 必要时加少量表), **不滥用 LLM** (能离线算的离线算).

### 3.1 阶段 1: 立刻做 (1~2 天) — 立竿见影

#### ① 抽出时机前移 + 差异可追溯

```sql
ALTER TABLE ai_chapter_variants
  ADD COLUMN kg_extracted_at   TIMESTAMP,
  ADD COLUMN kg_entity_count   INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN kg_event_count    INTEGER NOT NULL DEFAULT 0;
```

后端改造:
- `select_variant` 时也跑一次 `EntityExtractor`, 把"用户最终选了哪一版"对应的实体增量入 KG
- 在 `confirm_chapter` 之外, 任何一个变体被用户浏览时间超过 N 分钟, 也异步触发一次抽取 (走低优先级队列)

效果: **切换/丢弃/回退任何变体都不会丢知识**.

#### ② Critic 报告的 kg_conflicts 接入 KG

在 critic 的输出 JSON 中加一个字段 `conflicts_in_text` (形如 `[{quote, type, severity}]`):
- 写一个 `reconciliation.py` 模块, 在 critic 评分 < 7 时把 `conflicts_in_text` 写入 `ai_kg_events.attributes` 里 (key=`conflicts_observed`, value=[{chapter_no, quote, severity, resolved=false}])
- 下次 critic 评分时, 通过 `kg_context` 把这些未解决的冲突喂回给 critic, 让它必须 **对原冲突做出回应** (化解/承认/否定)

效果: **设定不会悄悄被破坏**.

#### ③ KG 上下文主动降噪 (RAG-lite)

新增一个 `rank_kg_for_chapter(chapter_no, planner_directions)` 函数:
- 对所有 `ai_kg_characters` 计算一个相关度:
  - 出现在本章 direction 的 `key_entities` 中 → 100
  - 上一章 confirmed 的 content 中出现过 → 80
  - 与本项目 `outline` 关键词重合 → 60
  - 上一章 direction 的 foreshadowing 中提到 → 50
  - 其它 → 20
- 按相关度排序, 取 top 30 写入 KG 上下文
- 路径: `services/kg_ranker.py` (纯 Python, 不调 LLM)

效果: **长篇后期 KG 不再臃肿**, 上限 30 个实体, 上下文不会爆 token.

---

### 3.2 阶段 2: 1 周左右 — 引入 3 个新维度

#### ④ 新增实体类型: Location

```sql
CREATE TABLE ai_kg_locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  entity_id TEXT NOT NULL,
  name TEXT NOT NULL,
  location_type TEXT,  -- 城市 / 建筑 / 秘境 / 区域 / 异空间
  attributes TEXT,     -- {坐标, 气候, 控制势力, 禁制, 描述}
  source_chapter_id INTEGER,
  created_at ...,
  updated_at ...,
  FOREIGN KEY ...,
  UNIQUE (project_id, entity_id)
);
```

**抽取出 Location**: EntityExtractor 的 JSON schema 增加 `locations[]` 字段, Writer 提示词加入 `#当前章节主场景` 必填位.

**冲突检测**: 当 Writer 写"角色从 A 城瞬间移动到 B 城"且 B 城与 A 城不在同一象限/未给交通工具时, critic 自动加 `kg_conflicts: [{type: "teleport", severity: "warn"}]`.

#### ⑤ 新增实体类型: PlotThread (伏笔/剧情线索)

```sql
CREATE TABLE ai_kg_plot_threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  thread_id TEXT NOT NULL,
  title TEXT NOT NULL,
  thread_type TEXT,           -- 伏笔 / 阴谋 / 角色弧 / 主题弧 / 承诺
  status TEXT,                -- open / hinting / resolving / resolved / dropped
  priority INTEGER,           -- 1..5, 5=主线
  introduced_chapter_id INTEGER,
  resolved_chapter_id INTEGER,
  related_entity_ids TEXT,    -- JSON: [char_001, evt_007]
  notes TEXT,
  source_chapter_id INTEGER,
  created_at ...,
  UNIQUE (project_id, thread_id)
);
```

**自动提取**: 每次 confirm_chapter 后, 调用一个新 Agent `ThreadExtractor`:
- 输入: 已确认的章节正文 + KG 中的全部 open threads
- 输出: `[{thread_id, action: "create|update|resolve|drop", ...}]`

**Planner 强制引用**: Planner 提示词新增 `#未结线索` 节, **必须** 在 `foreshadowing` 字段里选择至少 1 个 open thread, 否则兜底告警.

**UI 展示**: 在右侧参考面板加 "🔖 剧情线索" 折叠区, 默认展开, 列出 open threads 与进度条 (resolve 率 = resolved / total).

#### ⑥ 新增属性 schema 校验

不再让 LLM 把 attributes 写成任意 JSON. 改用结构化字段 + JSON for freeform extras:

```sql
-- 人物 (关键字段提列, attributes 仅承载角色专属信息)
ALTER TABLE ai_kg_characters
  ADD COLUMN role TEXT,                  -- 主角 / 配角 / 路人 / 反派
  ADD COLUMN faction TEXT,                -- 所属势力
  ADD COLUMN current_location_entity_id TEXT,  -- 引用 ai_kg_locations
  ADD COLUMN status TEXT,                -- 存活 / 失踪 / 死亡 / 转生
  ADD COLUMN first_appearance_chapter_id INTEGER,
  ADD COLUMN importance INTEGER;         -- 1..5

ALTER TABLE ai_kg_events
  ADD COLUMN in_story_time TEXT,         -- "第3年 暮春" 这种相对时间
  ADD COLUMN chapter_time_label TEXT,     -- "第3章 夜" 用于人类阅读
  ADD COLUMN importance INTEGER;
```

加一个 `_struct_validate(entity_type, attrs_dict) -> (cleaned_attrs, warnings)`, 强制 5 个必填字段, 拒绝任何未知字段, 警告可疑值 (年龄 = 0/负数/巨数).

效果: **每个实体字段可索引/可查询**, 跨章节一致性可程序化校验.

---

### 3.3 阶段 3: 2 周左右 — "不偏离" 的系统性防御

#### ⑦ 引入"偏离度"度量: CompassAgent

每章 confirm_chapter 前, 新 Agent `CompassAgent`:
- 输入: 大纲 (outline) + 根设定 + 当前章节 final_content + 全部 open threads
- 5 维评分: 主题偏离 / 大纲偏离 / 人物一致性 / 伏笔进度 / 文风一致
- 输出: 偏离报告, ≥ 3 项 warn 时**强提示用户** (非阻塞, 但 UI 红点)

#### ⑧ 跨章节"接龙"质量: 接缝检测

当章节 N 已被 confirm_chapter, 而用户开始生成章节 N+1 时, `creation_service.generate_chapter_streaming` 多调一个 `BridgeAgent`:
- 输入: 章节 N 末尾 800 字 + 章节 N+1 方向 + KG 中本应承接的 open threads
- 输出: 衔接质量 + 冲突检测 + 推荐的"开头钩子"

将 BridgeAgent 的输出作为 Writer 提示词前置项.

#### ⑨ Theme 追踪 (轻量)

不引入新表, 把 `style_pref` 中的 `themes` 字段作为 K-V 追踪:
- Planner 方向新增 `themes[]` 字段 (从 outline 抽取的关键词)
- confirm_chapter 时累积成 `project.themes_progress` (在 ai_projects 上加 JSON 列)
- Writer 提示词加入 `#主题进度 (上次 X / 共 Y)` 让它感知整体节奏

#### ⑩ 知识图谱可视化

在右栏参考面板加一个折叠的 "图谱" Tab, 用 dagre 或 vis.js 渲染:
- 节点: 人物 / 事件 / 地点
- 边: 关系
- 高亮: 当前章节涉及的实体 + open threads
- 交互: 节点点击展开 attributes, 边点击显示关系详情

---

## 4. 关键架构决策 (Why)

| 决策 | 备选 | 选谁 | 理由 |
|---|---|---|---|
| PlotThread 单独建表 | 用 Event 标 type=thread | **单独建表** | thread 有 lifecycle (open→resolved) 和 priority, 与 Event 正交 |
| 偏差检测 Agent 独立 vs 合并到 Critic | 合并到 Critic | **独立 CompassAgent** | 关注点不同: Critic 评"写得怎么样", Compass 评"偏没偏主线". 同 agent 会顾此失彼 |
| 主题跟踪 | 单独 Agent / 抽字段 | **抽字段** | 主题追踪是辅助信号, 不需要复杂推理, LLM 在生成时主动声明即可 |
| 抽取时机: confirm_chapter vs 每次保存 | 每次保存 | **保存时轻量抽取 (只增量), confirm 时完整抽取** | 平衡准确度与成本 |

---

## 5. 迁移计划 (零数据丢失)

由于是**纯增量**改造, 迁移策略:

1. **新表直接 CREATE** (SQLite `IF NOT EXISTS` 已支持)
2. **新字段直接 ALTER TABLE ADD COLUMN** (SQLite 允许, 默认值 NULL / DEFAULT 0)
3. **读取时兼容**: 旧数据 attributes 仍是 JSON, 新代码用 `attrs.get("...")` fallback 到新字段
4. **写入时双写**: 抽到新实体时同时把关键字段写到新列
5. **后台迁移脚本** (可选): 把 attributes 里的 role/faction/location 等迁移到新列
6. **回退方案**: 保留 attributes 字段, 新列只是"快查视图", 任意时刻可重建

预计影响: 旧项目无感知, 新项目立刻享受新结构.

---

## 6. 预期收益

| 指标 | 当前 | 阶段 1 后 | 阶段 2 后 | 阶段 3 后 |
|---|---|---|---|---|
| 设定一致性 bug 数 (用户反馈) | 中 | **低 ↓ 50%** | **极低 ↓ 80%** | **近乎 0** |
| 长篇后期伏笔漏掉率 | 高 (30 章后基本丢失) | 同左 | **低 ↓ 70%** | **低 ↓ 70%** |
| 抽取成功率 | ~70% (LLM JSON 解析失败) | ~85% (前移) | **~95% (Schema 校验)** | ~95% |
| 章节生成上下文 token 成本 | 高 (KG 越长越贵) | **降 40% (RAG 排序)** | 降 40% | 降 40% |
| 用户对"是否偏离主线"的判断 | 完全靠人工 | 同左 | **实时提示** | **实时提示 + 偏离报告** |

---

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 改表影响存量数据 | 老项目读不到新字段 | 加 `IF NOT EXISTS` 迁移, 读时兼容 attributes JSON |
| CompassAgent 增加 1 次 LLM 调用 | 生成时间 +5~10s | 走低优先级, 仅在用户点"确认章节"前异步触发 |
| 新表/字段加多 → KG 序列化文本变长 | 上下文拥挤 | 阶段 1 已加入 RAG 排序, top-30 上限 |
| 主题/伏笔追踪可能与大纲冲突 | 写偏反而出戏 | CompassAgent 把"偏离大纲"作为最高优先级 warn |

---

## 8. 优先级总表 (供后续排期)

| 阶段 | 编号 | 工作 | 估时 | 价值 |
|---|---|---|---|---|
| 1 | ① | 抽取前移到 select_variant + kg_extracted_at/计数 | 4h | ⭐⭐⭐ |
| 1 | ② | kg_conflicts 写回 KG + 回喂 | 4h | ⭐⭐⭐ |
| 1 | ③ | KG 上下文 RAG 排序 | 6h | ⭐⭐ |
| 2 | ④ | Location 实体 + 跨场景检测 | 1d | ⭐⭐⭐ |
| 2 | ⑤ | PlotThread 实体 + ThreadExtractor | 1.5d | ⭐⭐⭐ |
| 2 | ⑥ | 结构化字段 + 校验 | 1d | ⭐⭐⭐ |
| 3 | ⑦ | CompassAgent 偏离度度量 | 1.5d | ⭐⭐⭐ |
| 3 | ⑧ | BridgeAgent 接缝检测 | 1d | ⭐⭐ |
| 3 | ⑨ | Theme 字段追踪 | 4h | ⭐ |
| 3 | ⑩ | 图谱可视化 | 2d | ⭐⭐ |

> 总计: 约 8 ~ 10 天可完成阶段 1+2, 阶段 3 约 5~6 天. 建议先做阶段 1 (2 天内立竿见影).

---

## 9. 立即可实施的 1 个微改动 (本周)

在现有 KG 序列化里加一段 "⚠ 已知冲突" 列表:

```python
def _kg_warnings_for_prompt(kg) -> str:
    warnings = []
    for ev in kg.get("events", []):
        attrs = json.loads(ev.get("attributes") or "{}")
        for c in attrs.get("conflicts_observed", []):
            if not c.get("resolved"):
                warnings.append(f"- 事件 {ev['name']} 在第{c['chapter_no']}章存在未解决冲突: {c['quote']}")
    return "\n".join(warnings) or "(无)"
```

把它加入 `serialize_kg_for_prompt` 的末尾, 即时就能给所有 LLM 提示"这个设定在之前被打破过, 不要再犯".

---

**结论: 当前 KG 是"事后字典", 不是"创作护栏". 上面 10 步改造能让它成为创作者的"GPS + 黑匣子" — 既防止跑偏, 又能在跑偏时立刻告警.**

> 下一份待办: 阶段 1 的 ①/②/③ 改动 (`git diff` 级, 不需要新建表).
