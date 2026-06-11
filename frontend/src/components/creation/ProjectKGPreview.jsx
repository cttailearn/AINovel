// 项目级知识图谱: 列表 + 计数 + 手动编辑 (新增/修改/删除)
// - 读取: api.creation.getKG
// - 写入: api.creation.{create,update,delete}KGCharacter / Event / Location
// - 编辑通过 KGEntityEditorModal 完成; 删除需二次确认
import { useEffect, useState } from 'react';
import { ApiError, api } from '../../api/client.js';
import { useToast } from '../Toast/ToastProvider.jsx';
import { useConfirm } from '../../hooks/ConfirmProvider.jsx';
import { KGEntityEditorModal } from './KGEntityEditorModal.jsx';

function attrStr(attrs) {
  if (!attrs) return '';
  return Object.entries(attrs)
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('/') : String(v)}`)
    .join(' · ');
}

function KGNode({ node, type, onEdit, onDelete }) {
  const attrs = node.attributes || {};
  return (
    <div className={`creation-kg-node type-${type}`}>
      <div className="creation-kg-node-name">
        <span className="creation-kg-type-tag">{type === 'character' ? '人物' : '事件'}</span>
        <span className="creation-kg-node-title">{node.name}</span>
        <span className="creation-kg-node-actions">
          <button
            type="button"
            className="icon-btn kg-edit-btn"
            onClick={() => onEdit?.(node)}
            title="编辑"
            aria-label="编辑"
          >
            ✎
          </button>
          <button
            type="button"
            className="icon-btn kg-edit-btn danger"
            onClick={() => onDelete?.(node)}
            title="删除"
            aria-label="删除"
          >
            ×
          </button>
        </span>
      </div>
      {attrStr(attrs) && <div className="creation-kg-attrs muted small">{attrStr(attrs)}</div>}
    </div>
  );
}

function LocationRow({ loc, onEdit, onDelete }) {
  return (
    <li className="creation-location-item">
      <span
        className="creation-location-item-name"
        title={loc.name}
        onClick={() => onEdit?.(loc)}
        style={{ cursor: 'pointer' }}
      >
        {loc.name}
      </span>
      <span style={{ display: 'inline-flex', gap: 4 }}>
        {loc.location_type && (
          <span className="creation-location-type">{loc.location_type}</span>
        )}
        <button
          type="button"
          className="icon-btn kg-edit-btn"
          onClick={() => onEdit?.(loc)}
          title="编辑"
          aria-label="编辑"
          style={{ width: 22, height: 22, fontSize: 12 }}
        >
          ✎
        </button>
        <button
          type="button"
          className="icon-btn kg-edit-btn danger"
          onClick={() => onDelete?.(loc)}
          title="删除"
          aria-label="删除"
          style={{ width: 22, height: 22, fontSize: 12 }}
        >
          ×
        </button>
      </span>
    </li>
  );
}

function RelationRow({ rel, kind, onDelete, children }) {
  return (
    <li className="kg-rel-row">
      <span className="kg-rel-text">{children}</span>
      <button
        type="button"
        className="icon-btn kg-edit-btn danger"
        onClick={() => onDelete?.(rel, kind)}
        title="删除关系"
        aria-label="删除关系"
        style={{ width: 20, height: 20, fontSize: 11 }}
      >
        ×
      </button>
    </li>
  );
}

export function ProjectKGPreview({ projectId, refreshKey = 0, onChange }) {
  const toast = useToast();
  const confirmDialog = useConfirm();
  const [kg, setKg] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [editor, setEditor] = useState(null); // { mode, kind, initial }
  const [submitting, setSubmitting] = useState(false);

  const reload = async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.creation.getKG(projectId);
      setKg(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '加载图谱失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, refreshKey]);

  // 把写操作的结果冒泡给父级, 让父级能刷新 kg_full / 项目详情
  const notifyChanged = () => {
    onChange?.();
  };

  const openCreate = (kind) => setEditor({ mode: 'create', kind, initial: null });
  const openEdit = (kind, entity) => setEditor({ mode: 'edit', kind, initial: entity });
  const closeEditor = () => setEditor(null);

  const handleSubmit = async (payload) => {
    if (!editor || !projectId) return;
    setSubmitting(true);
    try {
      if (editor.kind === 'character') {
        if (editor.mode === 'create') {
          await api.creation.createKGCharacter(projectId, payload);
          toast.success('已新增人物到图谱');
        } else {
          await api.creation.updateKGCharacter(
            projectId, editor.initial.entity_id, payload
          );
          toast.success('已保存修改');
        }
      } else if (editor.kind === 'event') {
        if (editor.mode === 'create') {
          await api.creation.createKGEvent(projectId, payload);
          toast.success('已新增事件到图谱');
        } else {
          await api.creation.updateKGEvent(
            projectId, editor.initial.entity_id, payload
          );
          toast.success('已保存修改');
        }
      } else if (editor.kind === 'location') {
        if (editor.mode === 'create') {
          await api.creation.createKGLocation(projectId, payload);
          toast.success('已新增地点到图谱');
        } else {
          await api.creation.updateKGLocation(
            projectId, editor.initial.entity_id, payload
          );
          toast.success('已保存修改');
        }
      }
      closeEditor();
      await reload();
      notifyChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (kind, entity) => {
    const ok = await confirmDialog({
      title: '删除' + (kind === 'character' ? '人物' : kind === 'event' ? '事件' : '地点'),
      message: `确认删除「${entity.name}」?\n相关引用关系会一并清理, 不可恢复.`,
      danger: true,
      confirmText: '确认删除',
    });
    if (!ok) return;
    try {
      if (kind === 'character') {
        await api.creation.deleteKGCharacter(projectId, entity.entity_id);
      } else if (kind === 'event') {
        await api.creation.deleteKGEvent(projectId, entity.entity_id);
      } else if (kind === 'location') {
        await api.creation.deleteKGLocation(projectId, entity.entity_id);
      }
      toast.success('已删除');
      await reload();
      notifyChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '删除失败');
    }
  };

  const handleDeleteRelation = async (rel, kind) => {
    const ok = await confirmDialog({
      title: '删除关系',
      message: '确认删除这条关系?',
      danger: true,
      confirmText: '确认删除',
    });
    if (!ok) return;
    try {
      await api.creation.deleteKGRelation(projectId, kind, rel.id);
      toast.success('已删除关系');
      await reload();
      notifyChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '删除失败');
    }
  };

  if (loading && !kg) {
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
      <>
        <p className="muted small">
          暂无知识图谱数据. 确认章节后会自动抽取; 你也可以手动新增人物 / 事件 / 地点.
        </p>
        <div className="creation-kg-empty-add">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => openCreate('character')}>
            + 人物
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => openCreate('event')}>
            + 事件
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => openCreate('location')}>
            + 地点
          </button>
        </div>
        {editor && (
          <KGEntityEditorModal
            open
            mode={editor.mode}
            kind={editor.kind}
            initial={editor.initial}
            submitting={submitting}
            onSubmit={handleSubmit}
            onClose={closeEditor}
          />
        )}
      </>
    );
  }

  return (
    <div className="creation-kg-preview">
      <div className="creation-kg-stats muted small">
        人物 {chars.length} · 事件 {events.length} · 参与 {ce.length} · 人物关系 {cc.length} · 事件关系 {ee.length}
      </div>
      {chars.length > 0 && (
        <div className="creation-kg-section">
          <h5>
            <span>人物 ({chars.length})</span>
            <button
              type="button"
              className="kg-section-add"
              onClick={() => openCreate('character')}
              title="新增人物"
            >
              +
            </button>
          </h5>
          <div className="creation-kg-nodes">
            {chars.map((c) => (
              <KGNode
                key={c.id}
                node={c}
                type="character"
                onEdit={(n) => openEdit('character', n)}
                onDelete={(n) => handleDelete('character', n)}
              />
            ))}
          </div>
        </div>
      )}
      {events.length > 0 && (
        <div className="creation-kg-section">
          <h5>
            <span>事件 ({events.length})</span>
            <button
              type="button"
              className="kg-section-add"
              onClick={() => openCreate('event')}
              title="新增事件"
            >
              +
            </button>
          </h5>
          <div className="creation-kg-nodes">
            {events.map((e) => (
              <KGNode
                key={e.id}
                node={e}
                type="event"
                onEdit={(n) => openEdit('event', n)}
                onDelete={(n) => handleDelete('event', n)}
              />
            ))}
          </div>
        </div>
      )}
      {ce.length > 0 && (
        <div className="creation-kg-section">
          <h5>参与关系 (前 10)</h5>
          <ul className="creation-kg-rels">
            {ce.slice(0, 10).map((r) => (
              <RelationRow
                key={r.id}
                rel={r}
                kind="ce"
                onDelete={handleDeleteRelation}
              >
                <code>{r.source_entity_id}</code> --[{r.relation} / {r.role || '-'} / {r.action || '-'}]→ <code>{r.target_entity_id}</code>
              </RelationRow>
            ))}
          </ul>
        </div>
      )}
      {cc.length > 0 && (
        <div className="creation-kg-section">
          <h5>人物关系 (前 10)</h5>
          <ul className="creation-kg-rels">
            {cc.slice(0, 10).map((r) => (
              <RelationRow
                key={r.id}
                rel={r}
                kind="cc"
                onDelete={handleDeleteRelation}
              >
                <code>{r.source_entity_id}</code> --[{r.relation}]→ <code>{r.target_entity_id}</code>
              </RelationRow>
            ))}
          </ul>
        </div>
      )}

      {/* 地点放在末尾, 默认折叠 */}
      <div className="creation-kg-section">
        <h5>
          <span>地点 ({kg.locations ? kg.locations.length : 0})</span>
          <button
            type="button"
            className="kg-section-add"
            onClick={() => openCreate('location')}
            title="新增地点"
          >
            +
          </button>
        </h5>
        {kg.locations && kg.locations.length > 0 && (
          <ul className="creation-location-list">
            {kg.locations.map((l) => (
              <LocationRow
                key={l.id}
                loc={l}
                onEdit={(n) => openEdit('location', n)}
                onDelete={(n) => handleDelete('location', n)}
              />
            ))}
          </ul>
        )}
      </div>

      {editor && (
        <KGEntityEditorModal
          open
          mode={editor.mode}
          kind={editor.kind}
          initial={editor.initial}
          submitting={submitting}
          onSubmit={handleSubmit}
          onClose={closeEditor}
        />
      )}
    </div>
  );
}