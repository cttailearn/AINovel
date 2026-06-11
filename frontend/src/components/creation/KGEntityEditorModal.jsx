// KG 实体编辑器 (新增 / 编辑人物 / 事件 / 地点)
// 仅编辑最常用的可序列化字段 (name + attributes + 角色 / 状态 等),
// attributes 用 textarea 接受 JSON, 解析失败则按 key=value 行解析.
// 入参 mode: 'create' | 'edit'
// kind:   'character' | 'event' | 'location'
import { useEffect, useState } from 'react';

const KIND_LABELS = {
  character: '人物',
  event: '事件',
  location: '地点',
};

const STATUS_OPTIONS_CHARACTER = ['存活', '失踪', '死亡', '转生'];
const ROLE_OPTIONS_CHARACTER = ['主角', '配角', '反派', '路人'];
const TYPE_OPTIONS_LOCATION = ['城市', '建筑', '秘境', '区域', '异空间', '野外'];

function parseAttributesInput(text) {
  // 优先按 JSON 解析; 失败则按 "key=value" / "key: value" 逐行解析.
  if (!text || !text.trim()) return {};
  const trimmed = text.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    } catch (_) { /* fallback */ }
  }
  const out = {};
  for (const line of trimmed.split(/\r?\n/)) {
    const m = line.match(/^\s*([^:=]+)\s*[:=]\s*(.+)\s*$/);
    if (m) out[m[1].trim()] = m[2].trim();
  }
  return out;
}

function stringifyAttributes(obj) {
  if (!obj || typeof obj !== 'object') return '';
  const keys = Object.keys(obj);
  if (keys.length === 0) return '';
  return keys.map((k) => `${k}: ${obj[k]}`).join('\n');
}

export function KGEntityEditorModal({
  open,
  mode = 'create',
  kind = 'character',
  initial = null,
  onSubmit,
  onClose,
  submitting = false,
}) {
  const [name, setName] = useState('');
  const [entityId, setEntityId] = useState('');
  const [attributesText, setAttributesText] = useState('');
  // kind-specific fields
  const [role, setRole] = useState('');
  const [faction, setFaction] = useState('');
  const [status, setStatus] = useState('');
  const [importance, setImportance] = useState('');
  const [inStoryTime, setInStoryTime] = useState('');
  const [locationType, setLocationType] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setError('');
    setName(initial?.name || '');
    setEntityId(initial?.entity_id || '');
    setAttributesText(stringifyAttributes(initial?.attributes));
    setRole(initial?.role || '');
    setFaction(initial?.faction || '');
    setStatus(initial?.status || '');
    setImportance(
      typeof initial?.importance === 'number' ? String(initial.importance) : ''
    );
    setInStoryTime(initial?.in_story_time || '');
    setLocationType(initial?.location_type || '');
  }, [open, initial]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const isEdit = mode === 'edit';
  const titleVerb = isEdit ? '编辑' : '新建';
  const titleKind = KIND_LABELS[kind] || '实体';

  const handleSubmit = (e) => {
    e?.preventDefault?.();
    if (!name.trim()) {
      setError('请填写名称');
      return;
    }
    const payload = {
      name: name.trim(),
      attributes: parseAttributesInput(attributesText),
    };
    if (!isEdit && entityId.trim()) payload.entity_id = entityId.trim();
    if (kind === 'character') {
      if (role) payload.role = role;
      if (faction) payload.faction = faction;
      if (status) payload.status = status;
      if (importance) payload.importance = Number(importance);
    } else if (kind === 'event') {
      if (importance) payload.importance = Number(importance);
      if (inStoryTime) payload.in_story_time = inStoryTime;
    } else if (kind === 'location') {
      if (locationType) payload.location_type = locationType;
    }
    onSubmit?.(payload);
  };

  return (
    <div className="kg-detail-backdrop" onClick={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="kg-detail-modal" role="dialog" aria-modal="true">
        <button
          type="button"
          className="kg-detail-close"
          onClick={onClose}
          aria-label="关闭"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        <form className="kg-edit-form" onSubmit={handleSubmit}>
          <header className="kg-edit-head">
            <h3>{titleVerb}{titleKind}</h3>
            <p className="muted small">
              {isEdit ? `entity_id: ${initial?.entity_id || '—'}` : '修改后立即入图谱, LLM 后续抽取会按 entity_id 自动合并.'}
            </p>
          </header>

          <div className="kg-edit-body">
            <label className="form-row kg-edit-row">
              <span className="form-label">名称 <span className="required">*</span></span>
              <input
                type="text"
                className="form-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`如: 林晚`}
                maxLength={200}
                autoFocus
              />
            </label>

            {!isEdit && (
              <label className="form-row kg-edit-row">
                <span className="form-label">entity_id (可选)</span>
                <input
                  type="text"
                  className="form-input"
                  value={entityId}
                  onChange={(e) => setEntityId(e.target.value)}
                  placeholder="留空自动生成, 如 char_<随机>"
                  maxLength={64}
                />
              </label>
            )}

            {kind === 'character' && (
              <div className="form-row-2">
                <label className="form-row kg-edit-row">
                  <span className="form-label">角色</span>
                  <select
                    className="form-input"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                  >
                    <option value="">不指定</option>
                    {ROLE_OPTIONS_CHARACTER.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </label>
                <label className="form-row kg-edit-row">
                  <span className="form-label">势力</span>
                  <input
                    type="text"
                    className="form-input"
                    value={faction}
                    onChange={(e) => setFaction(e.target.value)}
                    placeholder="如: 青云门"
                    maxLength={120}
                  />
                </label>
                <label className="form-row kg-edit-row">
                  <span className="form-label">状态</span>
                  <select
                    className="form-input"
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                  >
                    <option value="">不指定</option>
                    {STATUS_OPTIONS_CHARACTER.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
                <label className="form-row kg-edit-row">
                  <span className="form-label">重要度 1-5</span>
                  <input
                    type="number"
                    className="form-input"
                    value={importance}
                    onChange={(e) => setImportance(e.target.value)}
                    min={1}
                    max={5}
                    placeholder="1..5"
                  />
                </label>
              </div>
            )}

            {kind === 'event' && (
              <div className="form-row-2">
                <label className="form-row kg-edit-row">
                  <span className="form-label">重要度 1-5</span>
                  <input
                    type="number"
                    className="form-input"
                    value={importance}
                    onChange={(e) => setImportance(e.target.value)}
                    min={1}
                    max={5}
                    placeholder="1..5"
                  />
                </label>
                <label className="form-row kg-edit-row">
                  <span className="form-label">故事内时间</span>
                  <input
                    type="text"
                    className="form-input"
                    value={inStoryTime}
                    onChange={(e) => setInStoryTime(e.target.value)}
                    placeholder="如: 第三章夜"
                    maxLength={120}
                  />
                </label>
              </div>
            )}

            {kind === 'location' && (
              <label className="form-row kg-edit-row">
                <span className="form-label">地点类型</span>
                <select
                  className="form-input"
                  value={locationType}
                  onChange={(e) => setLocationType(e.target.value)}
                >
                  <option value="">不指定</option>
                  {TYPE_OPTIONS_LOCATION.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
            )}

            <label className="form-row kg-edit-row">
              <span className="form-label">属性 (key: value 每行一条, 或 JSON)</span>
              <textarea
                className="form-input form-textarea"
                value={attributesText}
                onChange={(e) => setAttributesText(e.target.value)}
                rows={5}
                placeholder={
                  kind === 'character'
                    ? '性格: 内敛\n年龄: 18\n境界: 筑基期\n法宝: 青锋剑'
                    : kind === 'event'
                      ? '地点: 青云门大殿\n参与: 林晚, 苏尘\n影响: 引发宗门内乱'
                      : '坐标: 东海之滨\n气候: 温润\n控制势力: 青云门'
                }
              />
            </label>

            {error && <div className="kg-edit-error">{error}</div>}
          </div>

          <footer className="kg-edit-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onClose}
              disabled={submitting}
            >
              取消
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={submitting}
            >
              {submitting ? '保存中…' : (isEdit ? '保存修改' : '新增到图谱')}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}