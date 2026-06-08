// 项目级知识图谱简化预览 (MVP: 列表 + 计数, 后续可换成 KnowledgeGraphVisualizer)
import { useEffect, useState } from 'react';
import { ApiError, api } from '../../api/client.js';

function KGNode({ node, type }) {
  const attrs = node.attributes || {};
  const attrStr = Object.entries(attrs)
    .map(([k, v]) => `${k}=${v}`)
    .join(' · ');
  return (
    <div className={`creation-kg-node type-${type}`}>
      <div className="creation-kg-node-name">
        <span className="creation-kg-type-tag">{type === 'character' ? '人物' : '事件'}</span>
        {node.name}
      </div>
      {attrStr && <div className="creation-kg-attrs muted small">{attrStr}</div>}
    </div>
  );
}

export function ProjectKGPreview({ projectId, refreshKey = 0 }) {
  const [kg, setKg] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.creation.getKG(projectId);
        if (!cancelled) setKg(data);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : '加载图谱失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [projectId, refreshKey]);

  if (loading) {
    return <p className="muted small">加载图谱...</p>;
  }
  if (error) {
    return <p className="creation-error small">图谱加载失败: {error}</p>;
  }
  if (!kg) return null;

  const chars = kg.characters || [];
  const events = kg.events || [];
  const ce = kg.character_event_relations || [];
  const cc = kg.character_relations || [];
  const ee = kg.event_relations || [];
  const total = chars.length + events.length + ce.length + cc.length + ee.length;

  if (total === 0) {
    return (
      <p className="muted small">
        暂无知识图谱数据. 确认章节后会自动抽取, 或在「项目设定」中点击「种子图谱」从初始人物灌入.
      </p>
    );
  }

  return (
    <div className="creation-kg-preview">
      <div className="creation-kg-stats muted small">
        人物 {chars.length} · 事件 {events.length} · 参与 {ce.length} · 人物关系 {cc.length} · 事件关系 {ee.length}
      </div>
      {chars.length > 0 && (
        <div className="creation-kg-section">
          <h5>人物 ({chars.length})</h5>
          <div className="creation-kg-nodes">
            {chars.map((c) => <KGNode key={c.id} node={c} type="character" />)}
          </div>
        </div>
      )}
      {events.length > 0 && (
        <div className="creation-kg-section">
          <h5>事件 ({events.length})</h5>
          <div className="creation-kg-nodes">
            {events.map((e) => <KGNode key={e.id} node={e} type="event" />)}
          </div>
        </div>
      )}
      {ce.length > 0 && (
        <div className="creation-kg-section">
          <h5>参与关系 (前 10)</h5>
          <ul className="creation-kg-rels">
            {ce.slice(0, 10).map((r) => (
              <li key={r.id}>
                <code>{r.source_entity_id}</code> --[{r.relation} / {r.role || '-'} / {r.action || '-'}]--> <code>{r.target_entity_id}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
      {cc.length > 0 && (
        <div className="creation-kg-section">
          <h5>人物关系 (前 10)</h5>
          <ul className="creation-kg-rels">
            {cc.slice(0, 10).map((r) => (
              <li key={r.id}>
                <code>{r.source_entity_id}</code> --[{r.relation}]--> <code>{r.target_entity_id}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
