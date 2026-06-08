// 新建 / 编辑 AI 创作项目
import { useEffect, useState } from 'react';

const BLANK = {
  title: '',
  genre: '',
  worldview: '',
  outline: '',
  initial_concepts: [],
  style_pref: { 视角: '第三人称', 语气: '' },
  model_id: null,
};

function ConceptRow({ value, onChange, onRemove, idx }) {
  return (
    <div className="creation-concept-row">
      <input
        type="text"
        className="form-input"
        placeholder={`人物 ${idx + 1} 名字`}
        value={value.name || ''}
        onChange={(e) => onChange({ ...value, name: e.target.value })}
      />
      <input
        type="text"
        className="form-input"
        placeholder="简述 (性别 / 身份 / 性格...)"
        value={Object.entries(value.attributes || {}).map(([k, v]) => `${k}=${v}`).join('; ')}
        onChange={(e) => {
          const txt = e.target.value;
          const attrs = {};
          txt.split(';').map((s) => s.trim()).filter(Boolean).forEach((kv) => {
            const [k, ...rest] = kv.split('=');
            if (k && rest.length) attrs[k.trim()] = rest.join('=').trim();
          });
          onChange({ ...value, attributes: attrs });
        }}
      />
      <button
        type="button"
        className="icon-btn"
        onClick={onRemove}
        title="删除该人物"
        aria-label="删除"
      >
        ×
      </button>
    </div>
  );
}

export function ProjectForm({
  initial,
  models,
  onSubmit,
  onCancel,
  submitting = false,
  isEdit = false,
}) {
  const [form, setForm] = useState(() => ({
    ...BLANK,
    ...(initial || {}),
    initial_concepts: Array.isArray(initial?.initial_concepts)
      ? initial.initial_concepts.map((c) => ({
          name: c.name || '',
          attributes: c.attributes || {},
        }))
      : [],
    style_pref: initial?.style_pref || BLANK.style_pref,
    model_id: initial?.model_id ?? null,
  }));

  useEffect(() => {
    if (initial) {
      setForm({
        ...BLANK,
        ...initial,
        initial_concepts: Array.isArray(initial.initial_concepts)
          ? initial.initial_concepts.map((c) => ({
              name: c.name || '',
              attributes: c.attributes || {},
            }))
          : [],
        style_pref: initial.style_pref || BLANK.style_pref,
        model_id: initial.model_id ?? null,
      });
    }
  }, [initial]);

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const updateStyle = (k, v) => setForm((f) => ({ ...f, style_pref: { ...f.style_pref, [k]: v } }));

  const addConcept = () =>
    update('initial_concepts', [...(form.initial_concepts || []), { name: '', attributes: {} }]);
  const removeConcept = (idx) =>
    update(
      'initial_concepts',
      form.initial_concepts.filter((_, i) => i !== idx),
    );
  const updateConcept = (idx, v) =>
    update(
      'initial_concepts',
      form.initial_concepts.map((c, i) => (i === idx ? v : c)),
    );

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!form.title.trim()) return;
    onSubmit({
      ...form,
      initial_concepts: (form.initial_concepts || []).filter((c) => (c.name || '').trim()),
    });
  };

  return (
    <form className="creation-project-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <label className="form-label">
          标题 <span className="required">*</span>
        </label>
        <input
          type="text"
          className="form-input"
          value={form.title}
          onChange={(e) => update('title', e.target.value)}
          placeholder="如: 长安秘事"
          maxLength={200}
          required
        />
      </div>

      <div className="form-row form-row-2">
        <div>
          <label className="form-label">类型</label>
          <input
            type="text"
            className="form-input"
            value={form.genre}
            onChange={(e) => update('genre', e.target.value)}
            placeholder="如: 玄幻 / 都市 / 悬疑"
            maxLength={200}
          />
        </div>
        <div>
          <label className="form-label">使用模型</label>
          <select
            className="form-input"
            value={form.model_id ?? ''}
            onChange={(e) => update('model_id', e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">默认 (系统首个可用 chat 模型)</option>
            {(models || [])
              .filter((m) => (m.capability || 'chat') === 'chat' && m.enabled)
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.model_name})
                </option>
              ))}
          </select>
        </div>
      </div>

      <div className="form-row">
        <label className="form-label">世界观 / 设定</label>
        <textarea
          className="form-input form-textarea"
          rows={3}
          value={form.worldview}
          onChange={(e) => update('worldview', e.target.value)}
          placeholder="描述时代背景、地理、修炼体系/科技水平、势力格局等"
        />
      </div>

      <div className="form-row">
        <label className="form-label">总纲 / 故事走向</label>
        <textarea
          className="form-input form-textarea"
          rows={4}
          value={form.outline}
          onChange={(e) => update('outline', e.target.value)}
          placeholder="如: 主角因一桩旧案被贬江湖, 在复仇路上卷入朝堂阴谋, 最终发现身世之谜"
        />
      </div>

      <div className="form-row">
        <label className="form-label">初始人物 (可后续从「设定」导入)</label>
        <div className="creation-concepts">
          {(form.initial_concepts || []).length === 0 ? (
            <p className="muted small">点击下方按钮添加人物概念, 可在「种子图谱」一键灌入知识图谱</p>
          ) : (
            form.initial_concepts.map((c, i) => (
              <ConceptRow
                key={i}
                idx={i}
                value={c}
                onChange={(v) => updateConcept(i, v)}
                onRemove={() => removeConcept(i)}
              />
            ))
          )}
          <button type="button" className="btn btn-ghost btn-sm" onClick={addConcept}>
            + 添加人物
          </button>
        </div>
      </div>

      <div className="form-row form-row-2">
        <div>
          <label className="form-label">叙述视角</label>
          <select
            className="form-input"
            value={form.style_pref?.视角 || '第三人称'}
            onChange={(e) => updateStyle('视角', e.target.value)}
          >
            <option value="第一人称">第一人称</option>
            <option value="第三人称">第三人称</option>
            <option value="全知视角">全知视角</option>
          </select>
        </div>
        <div>
          <label className="form-label">语气 / 文风</label>
          <input
            type="text"
            className="form-input"
            value={form.style_pref?.语气 || ''}
            onChange={(e) => updateStyle('语气', e.target.value)}
            placeholder="如: 热血 / 冷峻 / 文艺 / 幽默"
          />
        </div>
      </div>

      <div className="form-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={submitting}>
          取消
        </button>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting || !form.title.trim()}
        >
          {submitting ? '保存中...' : isEdit ? '保存修改' : '创建项目'}
        </button>
      </div>
    </form>
  );
}
