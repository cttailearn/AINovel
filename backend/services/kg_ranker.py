"""KG RAG-lite 排序: 对知识图谱中的人物 / 事件 / 地点按相关度排序, 取 top-K.

设计目标
--------
- 长篇后期 KG 越来越大 (上百个实体), 全量塞给 LLM 浪费 token 且稀释注意力.
- 对每条实体计算一个 0-200+ 的相关度, 取 top-K=30.
- **零 ML 依赖**: 纯 Python 启发式 + 图算法, 不调 embedding 模型, 不调 LLM rerank.
- 优先级: 本章 direction 提到 > 上一章 confirmed 出现 > 与 outline 关键词重合 >
          上一章 foreshadowing 提到 > 章节共现 > 个体重要性 > 其它.
- Importance 加权: 主角/重要配角/主要反派始终靠前, 路人/小配角靠后.

算法组成 (按调用顺序)
---------------------
1. _keyword_set: 中文 n-gram (2-gram + 单字) + 停用词过滤
2. tfidf_score: TF-IDF 加权的方向→实体文本相关度 (替代裸 n-gram 重叠)
3. _score_entity: 线性加权 (importance + 直接命中 + TF-IDF + 个体覆盖)
4. _graph_signal: Personalized PageRank + BFS k-hop (沿人物↔事件↔地点传播)
5. _hard_rules: 必留 (主角/最近章节出场) / 必剔 (5 章前死的路人)
6. mmr_select: 多样性 rerank (避免 top-12 人物全是一家人)
7. rank_kg: 编排上述步骤, 产生最终的 top-K
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# 容量上限 (Writer/Critic/Planner 的 KG 上下文最多给 K 个实体)
DEFAULT_TOP_K = 30

# Importance >= 4 的实体 (主角/重要配角/主要反派) 永远保留, 不被截断
PROTECTED_IMPORTANCE = 4

# 每类型最多给的实体数 (防止某一类型霸榜)
PER_TYPE_QUOTA = {
    "character": 12,
    "event": 10,
    "location": 8,
}

# 中文停用词 (纯高频字, 标点之外几乎都应被过滤)
STOPWORDS: Set[str] = {
    # 单字
    "的", "了", "是", "在", "和", "也", "都", "就", "与", "或", "及",
    "把", "被", "给", "从", "向", "对", "为", "以", "让", "而", "但",
    "若", "则", "到", "于", "上", "下", "中", "里", "外", "内", "前",
    "后", "之", "其", "此", "那", "什", "么", "怎", "何", "谁", "哪",
    "有", "无", "未", "已", "曾", "将", "会", "能", "要", "可", "得",
    "做", "去", "来", "回", "过", "起", "出", "入", "又", "再", "才",
    "只", "便", "仍", "更", "最", "很", "太", "非", "不", "没",
    # 2-gram 高频虚词
    "之一", "之后", "之前", "之时", "之下", "之上", "之中", "之间",
    "也是", "就是", "还有", "没有", "可以", "应该", "可能", "一定",
    "突然", "竟然", "仍然", "已经", "正在", "常常", "往往", "居然",
}

# 2-gram 长度上限 (实体名很少 > 4 字)
MAX_NGRAM = 2


# ---------------------------------------------------------------------------
# 文本预处理
# ---------------------------------------------------------------------------


_PUNCT_RE = re.compile(r"[\s,。!?;:\-\(\)（）【】\"'\u201c\u201d\u2018\u2019、,《》<>]")


def _norm_name(name: str) -> str:
    return (name or "").strip()


def _strip_punct(text: str) -> str:
    return _PUNCT_RE.sub("", text or "")


def _keyword_set(text: str) -> Set[str]:
    """中文 n-gram 切分 (单字 + 2-gram) + 停用词过滤.

    例如 "林深处" → {林, 深, 处, 林深, 深处}. 停用词及其延伸 2-gram 都被去掉.
    """
    text = _strip_punct(text)
    if not text:
        return set()
    grams: Set[str] = set()
    # 单字
    for ch in text:
        if ch not in STOPWORDS:
            grams.add(ch)
    # n-gram (2-gram only by default)
    for i in range(len(text) - 1):
        g = text[i : i + 2]
        # 整个 2-gram 或任一字符是停用词 → 跳过
        if g in STOPWORDS or g[0] in STOPWORDS or g[1] in STOPWORDS:
            continue
        grams.add(g)
    return grams


def _overlap_score(a: Set[str], b: Set[str]) -> int:
    if not a or not b:
        return 0
    return len(a & b)


# ---------------------------------------------------------------------------
# 别名 (alias) 支持
# ---------------------------------------------------------------------------


def _aliases_of(entity: Dict[str, Any]) -> List[str]:
    """从 entity 字典里抽 aliases: 顶层 aliases 字段 或 attributes 别名/字号."""
    out: List[str] = []
    top = entity.get("aliases")
    if isinstance(top, list):
        out.extend(_norm_name(x) for x in top if _norm_name(x))
    elif isinstance(top, str) and top.strip():
        out.append(top.strip())
    attrs = entity.get("attributes") or {}
    if isinstance(attrs, dict):
        for k in ("别名", "alias", "aliases", "字号", "绰号"):
            v = attrs.get(k)
            if isinstance(v, list):
                out.extend(_norm_name(x) for x in v if _norm_name(x))
            elif isinstance(v, str) and v.strip():
                out.append(v.strip())
    # 去重, 排除与 name 相同的
    name = _norm_name(entity.get("name") or "")
    seen: Set[str] = {name}
    deduped: List[str] = []
    for a in out:
        if a and a not in seen:
            deduped.append(a)
            seen.add(a)
    return deduped


def _entity_text(entity: Dict[str, Any]) -> str:
    """实体可被检索的"全文": name + aliases + description + 几个关键 attributes."""
    parts: List[str] = []
    parts.append(_norm_name(entity.get("name") or ""))
    parts.extend(_aliases_of(entity))
    desc = _norm_name(entity.get("description") or "")
    if desc:
        parts.append(desc)
    attrs = entity.get("attributes") or {}
    if isinstance(attrs, dict):
        # 只取文本型 attribute, 跳过长列表/对象
        for k in ("身份", "性格", "种族", "门派", "势力", "当前状态",
                  "目的", "武器", "功法", "类型", "环境", "气候"):
            v = attrs.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# TF-IDF 评分 (替代裸 n-gram 重叠)
# ---------------------------------------------------------------------------


class _TfidfIndex:
    """实体语料的轻量 TF-IDF 索引; 离线随 KG 重建."""

    def __init__(self, kg: Dict[str, Any]) -> None:
        self.docs: Dict[str, Counter] = {}        # entity_id -> {term: tf}
        self.df: Counter = Counter()              # term -> 多少 entity 包含
        self.N: int = 0
        self._build(kg)

    def _build(self, kg: Dict[str, Any]) -> None:
        all_entities: List[Tuple[str, Dict[str, Any]]] = []
        for c in kg.get("characters") or []:
            eid = c.get("entity_id") or c.get("id")
            if eid:
                all_entities.append((str(eid), c))
        for e in kg.get("events") or []:
            eid = e.get("entity_id") or e.get("id")
            if eid:
                all_entities.append((str(eid), e))
        for l in kg.get("locations") or []:
            eid = l.get("entity_id") or l.get("id")
            if eid:
                all_entities.append((str(eid), l))
        self.N = len(all_entities)
        for eid, ent in all_entities:
            terms = _keyword_set(_entity_text(ent))
            tf = Counter(terms)
            self.docs[eid] = tf
            for t in terms:
                self.df[t] += 1

    def score(self, eid: str, query_terms: Set[str]) -> float:
        """计算 entity 对 query 的 TF-IDF cosine (这里用归一化内积, 避免开方)."""
        if not query_terms or eid not in self.docs:
            return 0.0
        tf = self.docs[eid]
        if not tf:
            return 0.0
        # entity 自身 norm
        ent_norm = 0.0
        for t, f in tf.items():
            idf = math.log((self.N + 1) / (1 + self.df.get(t, 0))) + 1
            ent_norm += (f * idf) ** 2
        ent_norm = math.sqrt(ent_norm) or 1.0
        # query norm
        q_norm = 0.0
        q_vec: Dict[str, float] = {}
        for t in query_terms:
            if t not in tf:
                continue
            idf = math.log((self.N + 1) / (1 + self.df.get(t, 0))) + 1
            w = tf[t] * idf
            q_vec[t] = w
            q_norm += w * w
        q_norm = math.sqrt(q_norm) or 1.0
        # dot
        dot = sum(q_vec[t] * q_vec[t] for t in q_vec)  # 双方都用 tf-idf
        return dot / (ent_norm * q_norm)


# ---------------------------------------------------------------------------
# 图信号: Personalized PageRank + k-hop
# ---------------------------------------------------------------------------


def _build_kg_graph(kg: Dict[str, Any]) -> Dict[str, List[Tuple[str, float]]]:
    """从 KG 三类关系构邻接表 (双向)."""
    graph: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    for r in kg.get("character_relations") or []:
        s = str(r.get("source_entity_id") or "")
        t = str(r.get("target_entity_id") or "")
        if s and t:
            graph[s].append((t, 1.0))
            graph[t].append((s, 1.0))
    for r in kg.get("character_event_relations") or []:
        s = str(r.get("source_entity_id") or "")
        t = str(r.get("target_entity_id") or "")
        if s and t:
            graph[s].append((t, 0.9))   # 人物-事件权重略低
            graph[t].append((s, 0.9))
    for r in kg.get("event_relations") or []:
        s = str(r.get("source_entity_id") or "")
        t = str(r.get("target_entity_id") or "")
        if s and t:
            graph[s].append((t, 0.8))
            graph[t].append((s, 0.8))
    return graph


def _personalized_pagerank(
    graph: Dict[str, List[Tuple[str, float]]],
    source_ids: Set[str],
    *,
    alpha: float = 0.85,
    iterations: int = 30,
    tol: float = 1e-4,
) -> Dict[str, float]:
    """从 source_ids 节点出发做 PPR. 返回每个节点的 0-1 分数."""
    nodes: Set[str] = set(graph.keys())
    for u in list(graph.keys()):
        for v, _ in graph[u]:
            nodes.add(v)
    nodes |= {s for s in source_ids if s}
    if not nodes or not source_ids:
        return {n: 0.0 for n in nodes}

    # 节点入度 (出度边数, 用于随机跳转均匀分配)
    out_weight: Dict[str, float] = {n: 0.0 for n in nodes}
    for u in graph:
        if u not in nodes:
            continue
        for v, w in graph[u]:
            if v in nodes:
                out_weight[u] += w
    pr = {n: (1.0 / len(source_ids) if n in source_ids else 0.0) for n in nodes}
    teleport = {n: (1.0 / len(source_ids) if n in source_ids else 0.0) for n in nodes}
    for _ in range(iterations):
        new_pr: Dict[str, float] = {n: (1 - alpha) * teleport[n] for n in nodes}
        for u, neighs in graph.items():
            if u not in nodes or not neighs or out_weight[u] == 0:
                continue
            share = alpha * pr[u] / out_weight[u]
            for v, w in neighs:
                if v in nodes:
                    new_pr[v] += share * w
        # 收敛检测
        diff = sum(abs(new_pr[n] - pr[n]) for n in nodes)
        pr = new_pr
        if diff < tol:
            break
    return pr


def _k_hop_neighbors(
    graph: Dict[str, List[Tuple[str, float]]],
    source_ids: Set[str],
    k: int = 2,
) -> Dict[str, int]:
    """BFS k-hop: 返回 entity_id → 距最近 source 的 hop 数 (未到达则不入返回)."""
    distances: Dict[str, int] = {}
    frontier = set(source_ids)
    for d in range(0, k + 1):
        next_frontier: Set[str] = set()
        for u in frontier:
            if u not in distances:
                distances[u] = d
            for v, _ in graph.get(u, []):
                if v not in distances:
                    distances[v] = d
                    next_frontier.add(v)
        frontier = next_frontier
        if not frontier:
            break
    return distances


# ---------------------------------------------------------------------------
# 硬规则 (无 ML, 业务逻辑驱动)
# ---------------------------------------------------------------------------


def _hard_keep_filter(
    candidates: List[Dict[str, Any]],
    kind: str,
    *,
    recent_chapter_appearances: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """必留规则: importance >= 4 (主角/重要反派) + 最近 3 章出现过."""
    recent = recent_chapter_appearances or {}
    keep: List[Dict[str, Any]] = []
    for c in candidates:
        imp = _importance_of(c, kind)
        eid = str(c.get("entity_id") or "")
        if imp >= PROTECTED_IMPORTANCE:
            keep.append(c)
        elif eid in recent and recent[eid] >= 1:
            keep.append(c)
    return keep


def _hard_drop_filter(
    candidates: List[Dict[str, Any]],
    kind: str,
    *,
    current_chapter_no: int = 0,
) -> List[Dict[str, Any]]:
    """必剔规则: 死亡路人 且 N 章前最后出现, 不再召回."""
    drop: List[Dict[str, Any]] = []
    if kind != "character":
        return drop
    for c in candidates:
        status = (c.get("status") or "").strip()
        importance = _importance_of(c, kind)
        last_ch = c.get("last_appearance_chapter_no") or 0
        if status in ("死亡", "dead", "转生", "reincarnated") and importance < 3:
            if current_chapter_no and last_ch and (current_chapter_no - last_ch) >= 5:
                drop.append(c)
    return drop


# ---------------------------------------------------------------------------
# MMR 多样性 rerank
# ---------------------------------------------------------------------------


def _entity_char_set(entity: Dict[str, Any]) -> Set[str]:
    return _keyword_set(_entity_text(entity))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mmr_select(
    candidates: List[Tuple[float, Dict[str, Any]]],
    k: int,
    *,
    lambda_param: float = 0.65,
) -> List[Dict[str, Any]]:
    """Maximal Marginal Relevance - 贪心选 k 个: 既相关又互不重叠.

    candidates: [(score, entity)] 已按 score 降序, 取前 N >> k.
    """
    selected: List[Dict[str, Any]] = []
    selected_chars: List[Set[str]] = []
    pool = list(candidates)  # 复制, 我们要删元素

    while len(selected) < k and pool:
        best_idx = 0
        best_mmr = -1e18
        for i, (score, ent) in enumerate(pool):
            chars = _entity_char_set(ent)
            if not selected_chars:
                diversity = 0.0
            else:
                diversity = max(_jaccard(chars, sc) for sc in selected_chars)
            mmr = lambda_param * score - (1 - lambda_param) * diversity * 100
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i
        score, ent = pool.pop(best_idx)
        selected.append(ent)
        selected_chars.append(_entity_char_set(ent))
    return selected


# ---------------------------------------------------------------------------
# 主排序函数
# ---------------------------------------------------------------------------


def _importance_of(entity: Dict[str, Any], kind: str) -> int:
    imp = entity.get("importance")
    if isinstance(imp, (int, float)) and 0 < imp <= 5:
        return int(imp)
    if kind == "character":
        role = (entity.get("role") or "").strip()
        if role in ("主角", "main"):
            return 5
        if role in ("配角", "重要配角", "supporting"):
            return 3
        if role in ("反派", "重要反派", "villain"):
            return 4
        if role in ("路人", "minor"):
            return 1
    if kind == "event":
        name = entity.get("name") or ""
        if "主" in name or "核心" in name or "终" in name or "开" in name:
            return 4
    return 2


def out_for(out: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    """Helper: 'character' → 'characters', 'event' → 'events'."""
    if kind + "s" in out:
        return out[kind + "s"]
    if kind + "es" in out:
        return out[kind + "es"]
    if kind in out:
        return out[kind]
    return []


def rank_kg(
    kg: Dict[str, List[Dict[str, Any]]],
    *,
    planner_directions: Optional[List[Dict[str, Any]]] = None,
    last_chapter_content: str = "",
    outline: str = "",
    last_directions: Optional[List[Dict[str, Any]]] = None,
    top_k: int = DEFAULT_TOP_K,
    current_chapter_no: int = 0,
    # 可选: chapter-level co-occurrence counts {char_a: {char_b: cnt}}
    co_occurrence: Optional[Dict[str, Dict[str, int]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """给 KG 中的人物/事件/地点打分, 返回排序后 + 截断的 KG dict.

    组合信号 (线性加权, 顺序近似影响力):
      - importance × 8                              基础身份
      - direction.key_entities / foreshadowing     直接命中 (100/80)
      - TF-IDF cosine (name+aliases+description)   文本相关度
      - TF-IDF cosine (outline + last_chapter)     上下文相关度
      - co-occurrence boost                         章节级共现
      - Personalized PageRank (direction→)         图传播
      - k-hop distance bonus                        图邻近
      - hard rules (必留/必剔)
      - MMR diversity (避免一家亲)
    """
    # ---- 1. 解析 direction / 上下文 ----
    direction_entities: Set[str] = set()
    direction_foreshadowing: Set[str] = set()
    direction_entity_ids: Set[str] = set()  # 用于 PPR 起点
    if planner_directions:
        for d in planner_directions:
            for e in d.get("key_entities") or []:
                norm = _norm_name(e)
                direction_entities.add(norm)
            for f in d.get("foreshadowing") or []:
                direction_foreshadowing.add(_norm_name(f))
            for t in d.get("themes") or []:
                direction_foreshadowing.add(_norm_name(t))

    # 把 direction_entities 同时映射到 entity_id (PPR 起点需要)
    name_to_id: Dict[str, str] = {}
    for lst_key in ("characters", "events", "locations"):
        for ent in kg.get(lst_key) or []:
            eid = str(ent.get("entity_id") or "")
            name = _norm_name(ent.get("name") or "")
            if eid and name:
                name_to_id.setdefault(name, eid)
                for a in _aliases_of(ent):
                    name_to_id.setdefault(a, eid)
    for n in direction_entities:
        if n in name_to_id:
            direction_entity_ids.add(name_to_id[n])

    last_chapter_kg = _keyword_set(last_chapter_content[:2000])
    outline_kg = _keyword_set(outline)

    last_foreshadowing_kg: Set[str] = set()
    if last_directions:
        for d in last_directions:
            for f in d.get("foreshadowing") or []:
                last_foreshadowing_kg.add(_norm_name(f))

    # ---- 2. 离线构建 TF-IDF 索引 ----
    tfidf = _TfidfIndex(kg)

    # ---- 3. 构建 KG 图, 跑 PPR + k-hop ----
    graph = _build_kg_graph(kg)
    if direction_entity_ids:
        ppr_scores = _personalized_pagerank(graph, direction_entity_ids)
        hop_distances = _k_hop_neighbors(graph, direction_entity_ids, k=2)
    else:
        ppr_scores = {}
        hop_distances = {}

    # ---- 4. 给每个实体打分 ----
    scored: Dict[str, List[Tuple[float, Dict[str, Any]]]] = {
        "character": [],
        "event": [],
        "location": [],
    }

    def _score(ent: Dict[str, Any], kind: str) -> float:
        eid = str(ent.get("entity_id") or "")
        names = [_norm_name(ent.get("name") or "")] + _aliases_of(ent)
        names = [n for n in names if n]
        if not eid or not names:
            return 0.0

        score = 0.0
        importance = _importance_of(ent, kind)
        score += importance * 8

        # 直接命中 (任意一个 name/alias 在 direction.key_entities 里)
        if any(n in direction_entities for n in names):
            score += 100
        if any(n in direction_foreshadowing for n in names):
            score += 80

        # TF-IDF: entity 全文 (含 aliases + description) vs 上下文
        ent_terms = _keyword_set(_entity_text(ent))
        if ent_terms and last_chapter_kg:
            score += tfidf.score(eid, last_chapter_kg) * 30
        if ent_terms and outline_kg:
            score += tfidf.score(eid, outline_kg) * 25
        if ent_terms and last_foreshadowing_kg:
            score += tfidf.score(eid, last_foreshadowing_kg) * 20

        # 兜底: 实体 name 的 n-gram 与上下文的裸重叠 (TF-IDF 0 命中时仍能召回)
        if last_chapter_kg:
            score += _overlap_score(_keyword_set(names[0]), last_chapter_kg) * 2
        if outline_kg:
            score += _overlap_score(_keyword_set(names[0]), outline_kg) * 1.5

        # 章节共现 boost: 与 direction_entity_ids 中节点的共现频次
        if co_occurrence and direction_entity_ids and eid in co_occurrence:
            pmi_total = 0.0
            for src in direction_entity_ids:
                if src == eid:
                    continue
                cnt = co_occurrence.get(src, {}).get(eid, 0)
                if cnt > 0:
                    pmi_total += math.log1p(cnt)
            score += pmi_total * 4

        # PPR 分数 (0-1 → 0-30)
        ppr = ppr_scores.get(eid, 0.0)
        score += ppr * 30

        # k-hop 距离 bonus
        dist = hop_distances.get(eid)
        if dist is not None and dist > 0:
            score += max(0, 12 - dist * 5)

        # 实体 description 命中 (强信号, 表明 description 写得好)
        desc = _norm_name(ent.get("description") or "")
        if desc:
            desc_kg = _keyword_set(desc)
            if desc_kg & last_chapter_kg:
                score += 10
            if desc_kg & outline_kg:
                score += 6

        return score

    for ch in kg.get("characters") or []:
        scored["character"].append((_score(ch, "character"), ch))
    for ev in kg.get("events") or []:
        scored["event"].append((_score(ev, "event"), ev))
    for loc in kg.get("locations") or []:
        scored["location"].append((_score(loc, "location"), loc))

    # ---- 5. 排序 + 硬规则过滤 ----
    out: Dict[str, List[Dict[str, Any]]] = {
        "characters": [],
        "events": [],
        "locations": [],
    }

    for kind, items in scored.items():
        items.sort(key=lambda x: -x[0])
        quota = PER_TYPE_QUOTA.get(kind, top_k)

        # 必留规则: importance>=4 + 最近出场
        keep = _hard_keep_filter([e for _, e in items], kind)
        for e in keep:
            if e not in out_for(out, kind):
                out_for(out, kind).append(e)

        # 必剔规则 (仅 character)
        drops = set(_hard_drop_filter(
            [e for _, e in items], kind,
            current_chapter_no=current_chapter_no,
        ))

        # 剩余候选用 MMR 多样性选取
        remaining = [(s, e) for s, e in items if e not in drops and e not in out_for(out, kind)]
        # 多取些候选, 让 MMR 有空间
        take = min(max(quota * 3, quota + 4), len(remaining))
        picked = mmr_select(remaining[:take], quota, lambda_param=0.65)
        out_for(out, kind).extend(picked)

        # 截断到 quota (重要性 ≥4 突破配额上界)
        bucket = out_for(out, kind)
        if len(bucket) > quota * 2:
            del bucket[quota * 2 :]

    # ---- 6. 关系裁剪: 跟着实体白名单 ----
    allowed_chars = {e.get("entity_id") for e in out["characters"]}
    allowed_events = {e.get("entity_id") for e in out["events"]}
    allowed_locs = {e.get("entity_id") for e in out["locations"]}

    for kind, allowed in (
        ("character_relations", allowed_chars),
        ("event_relations", allowed_events),
        ("character_event_relations", None),
    ):
        rels = []
        for r in kg.get(kind) or []:
            s = str(r.get("source_entity_id") or "")
            t = str(r.get("target_entity_id") or "")
            if kind == "character_relations":
                if s in allowed or t in allowed:
                    rels.append(r)
            elif kind == "event_relations":
                if s in allowed or t in allowed:
                    rels.append(r)
            else:  # character_event_relations
                if s in allowed_chars or t in allowed_events:
                    rels.append(r)
        out[kind] = rels

    return out


# ---------------------------------------------------------------------------
# 已知冲突 / 伏笔 → 提示词片段
# ---------------------------------------------------------------------------


def _kg_warnings_for_prompt(kg: Dict[str, Any]) -> str:
    """从 KG 中提取已知冲突/未解决伏笔, 给 LLM 一个明确提醒."""
    warnings: List[str] = []
    for ev in kg.get("events") or []:
        attrs = ev.get("attributes") or {}
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs) if attrs.strip() else {}
            except (TypeError, ValueError):
                attrs = {}
        for c in attrs.get("conflicts_observed") or []:
            if not c.get("resolved"):
                ch_no = c.get("chapter_no", "?")
                quote = (c.get("quote") or "").strip()[:60]
                warnings.append(
                    f"⚠ 事件『{ev.get('name', '?')}』在第{ch_no}章存在未解决冲突: {quote}"
                )
    for ch in kg.get("characters") or []:
        attrs = ch.get("attributes") or {}
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs) if attrs.strip() else {}
            except (TypeError, ValueError):
                attrs = {}
        for c in attrs.get("conflicts_observed") or []:
            if not c.get("resolved"):
                ch_no = c.get("chapter_no", "?")
                quote = (c.get("quote") or "").strip()[:60]
                warnings.append(
                    f"⚠ 人物『{ch.get('name', '?')}』在第{ch_no}章存在未解决冲突: {quote}"
                )
    return "\n".join(warnings) or "(无)"


# ---------------------------------------------------------------------------
# 章节级共现矩阵 (给 rank_kg 的 co_occurrence 参数用)
# ---------------------------------------------------------------------------


def compute_chapter_co_occurrence(
    chapter_text: str,
    entities: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    """统计本章中实体两两共现次数: 同一段 / 同一句 / 隔 N 字以内.

    返回 {(entity_a, entity_b): cnt}. 接收 entity dict 列表 (含 name/aliases).
    纯字符串扫描, 不调 ML.
    """
    text = _strip_punct(chapter_text)
    if not text or not entities:
        return {}

    # 用所有 name + aliases 做关键词列表, 长度 2-6 字
    keyword_to_eid: Dict[str, str] = {}
    for ent in entities:
        eid = str(ent.get("entity_id") or "")
        if not eid:
            continue
        candidates = [_norm_name(ent.get("name") or "")] + _aliases_of(ent)
        for c in candidates:
            if 2 <= len(c) <= 6:  # 太短易误命中, 太长无意义
                keyword_to_eid.setdefault(c, eid)

    if not keyword_to_eid:
        return {}

    # 句子级共现 (按 。！？ 切)
    sentences = re.split(r"[。！？!?\n]+", chapter_text)
    pair_count: Dict[Tuple[str, str], int] = defaultdict(int)
    for sent in sentences:
        s_clean = _strip_punct(sent)
        if not s_clean:
            continue
        # 本句出现的实体
        present: Set[str] = set()
        for kw, eid in keyword_to_eid.items():
            if kw in s_clean:
                present.add(eid)
        # 两两配对 (无向, 字典序去重)
        present_list = sorted(present)
        for i in range(len(present_list)):
            for j in range(i + 1, len(present_list)):
                pair = (present_list[i], present_list[j])
                pair_count[pair] += 1

    # 转为嵌套 dict
    out: Dict[str, Dict[str, int]] = defaultdict(dict)
    for (a, b), cnt in pair_count.items():
        out[a][b] = cnt
        out[b][a] = cnt
    return dict(out)