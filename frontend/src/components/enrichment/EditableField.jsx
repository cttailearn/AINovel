import { useEffect, useRef, useState } from 'react';

/**
 * 可内联编辑的字段, 用于「AI 加料工坊」中让用户修改 AI 抽取的拆解结果.
 *
 * 用法:
 *   <EditableField
 *     value={detail.summary}
 *     onSave={async (v) => await api.enrichment.updateDetail(cid, { summary: v })}
 *     multiline rows={4}
 *     placeholder="尚未生成"
 *   />
 *
 * - 始终有"编辑"按钮进入编辑态
 * - 编辑时显示 textarea / input + 保存 / 取消
 * - 保存成功后回到只读态, 并触发 onSave
 */
export function EditableField({
  value,
  onSave,
  multiline = false,
  rows = 3,
  placeholder = '尚未生成',
  emptyHint = '（未填写, 点"编辑"补充）',
  type = 'text',
  className = '',
  disabled = false,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || '');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const taRef = useRef(null);

  // 外部 value 变化时 (例如新一次 AI 抽取完成), 若当前不在编辑, 同步
  useEffect(() => {
    if (!editing) {
      setDraft(value || '');
      setDirty(false);
    }
  }, [value, editing]);

  const handleEdit = () => {
    if (disabled) return;
    setDraft(value || '');
    setDirty(false);
    setEditing(true);
    setTimeout(() => {
      if (taRef.current) {
        taRef.current.focus();
        if (multiline && typeof taRef.current.setSelectionRange === 'function') {
          taRef.current.setSelectionRange(
            taRef.current.value.length,
            taRef.current.value.length
          );
        }
      }
    }, 0);
  };

  const handleCancel = () => {
    setDraft(value || '');
    setDirty(false);
    setEditing(false);
  };

  const handleSave = async () => {
    if (saving) return;
    if (!onSave) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
      setDirty(false);
    } catch {
      // 错误由调用方 toast, 这里保持编辑态
    } finally {
      setSaving(false);
    }
  };

  const isEmpty = !value || (typeof value === 'string' && value.trim() === '');

  if (editing) {
    return (
      <div className={`editable-field editing ${className}`}>
        {multiline ? (
          <textarea
            ref={taRef}
            className="editable-field-input"
            rows={rows}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setDirty(true);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') handleCancel();
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSave();
            }}
            disabled={saving}
          />
        ) : (
          <input
            ref={taRef}
            className="editable-field-input"
            type={type}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setDirty(true);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') handleCancel();
              if (e.key === 'Enter') handleSave();
            }}
            disabled={saving}
          />
        )}
        <div className="editable-field-actions">
          <button
            type="button"
            className="editable-field-btn primary"
            onClick={handleSave}
            disabled={saving || !dirty}
            title="保存 (Ctrl/Cmd+Enter)"
          >
            {saving ? <span className="loading-spinner small" /> : '保存'}
          </button>
          <button
            type="button"
            className="editable-field-btn ghost"
            onClick={handleCancel}
            disabled={saving}
          >
            取消
          </button>
          {dirty && <span className="editable-field-hint">已修改</span>}
        </div>
      </div>
    );
  }

  return (
    <div className={`editable-field ${isEmpty ? 'empty' : ''} ${className}`}>
      {isEmpty ? (
        <p className="editable-field-empty">{emptyHint}</p>
      ) : multiline ? (
        <p className="editable-field-text">{value}</p>
      ) : (
        <span className="editable-field-text">{value}</span>
      )}
      <button
        type="button"
        className="editable-field-edit"
        onClick={handleEdit}
        disabled={disabled}
        title={isEmpty ? '补充内容' : '编辑'}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
          <path
            d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"
            stroke="currentColor"
            strokeWidth="2"
          />
        </svg>
        {isEmpty ? '补充' : '编辑'}
      </button>
    </div>
  );
}

/**
 * 列表型可编辑字段 (用于登场人物 / 关键事件).
 * - items: [{name, description}]
 * - onSave: (newItems) => Promise
 */
export function EditableListField({
  items = [],
  onSave,
  placeholder = '点击「+」添加',
  nameLabel = '名称',
  descLabel = '描述',
  disabled = false,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(items);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(items);
  }, [items, editing]);

  const handleAdd = () => {
    setDraft((d) => [...d, { name: '', description: '' }]);
  };
  const handleRemove = (idx) => {
    setDraft((d) => d.filter((_, i) => i !== idx));
  };
  const handleChange = (idx, key, val) => {
    setDraft((d) =>
      d.map((it, i) => (i === idx ? { ...it, [key]: val } : it))
    );
  };
  const handleSave = async () => {
    if (saving) return;
    // 过滤空名字
    const cleaned = draft.filter(
      (it) => (it.name || '').trim() !== '' || (it.description || '').trim() !== ''
    );
    setSaving(true);
    try {
      await onSave(cleaned);
      setEditing(false);
    } catch {
      // 保持编辑
    } finally {
      setSaving(false);
    }
  };
  const handleCancel = () => {
    setDraft(items);
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="editable-field editing">
        <ul className="editable-list-edit">
          {draft.map((it, i) => (
            // eslint-disable-next-line react/no-array-index-key
            <li key={i} className="editable-list-row">
              <input
                className="editable-list-input"
                type="text"
                placeholder={nameLabel}
                value={it.name || ''}
                onChange={(e) => handleChange(i, 'name', e.target.value)}
                disabled={saving}
              />
              <input
                className="editable-list-input desc"
                type="text"
                placeholder={descLabel}
                value={it.description || ''}
                onChange={(e) => handleChange(i, 'description', e.target.value)}
                disabled={saving}
              />
              <button
                type="button"
                className="editable-list-remove"
                onClick={() => handleRemove(i)}
                disabled={saving}
                title="删除"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <div className="editable-list-add-row">
          <button
            type="button"
            className="editable-field-btn ghost"
            onClick={handleAdd}
            disabled={saving}
          >
            + 添加
          </button>
        </div>
        <div className="editable-field-actions">
          <button
            type="button"
            className="editable-field-btn primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? <span className="loading-spinner small" /> : '保存'}
          </button>
          <button
            type="button"
            className="editable-field-btn ghost"
            onClick={handleCancel}
            disabled={saving}
          >
            取消
          </button>
        </div>
      </div>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div className="editable-field empty">
        <p className="editable-field-empty">（无）</p>
        <button
          type="button"
          className="editable-field-edit"
          onClick={() => setEditing(true)}
          disabled={disabled}
        >
          + 添加
        </button>
      </div>
    );
  }

  return (
    <div className="editable-field">
      <ul className="editable-list-readonly">
        {items.map((it, i) => (
          // eslint-disable-next-line react/no-array-index-key
          <li key={i} className="editable-list-readonly-item">
            <strong>{it.name || `条目 ${i + 1}`}</strong>
            {it.description && <span> — {it.description}</span>}
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="editable-field-edit"
        onClick={() => setEditing(true)}
        disabled={disabled}
        title="编辑"
      >
        编辑
      </button>
    </div>
  );
}

/**
 * 场景标签 - 多选 chip 编辑.
 * options: 候选项数组
 * value: string (当前选中的标签)
 * onSave: (newValue) => Promise
 */
export function SceneTagField({
  value = '',
  options = [],
  onSave,
  disabled = false,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <div className="editable-field editing">
        <div className="scene-tag-chips-edit">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              className={`scene-tag-chip ${draft === opt ? 'active' : ''}`}
              onClick={() => setDraft(opt)}
              disabled={saving}
            >
              {opt}
            </button>
          ))}
        </div>
        <input
          className="editable-field-input"
          type="text"
          placeholder="或自定义场景标签"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={saving}
        />
        <div className="editable-field-actions">
          <button
            type="button"
            className="editable-field-btn primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? <span className="loading-spinner small" /> : '保存'}
          </button>
          <button
            type="button"
            className="editable-field-btn ghost"
            onClick={() => {
              setDraft(value);
              setEditing(false);
            }}
            disabled={saving}
          >
            取消
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="editable-field">
      {value ? (
        <span className="enrichment-side-panel-scene-tag">{value}</span>
      ) : (
        <span className="editable-field-empty">（未标记）</span>
      )}
      <button
        type="button"
        className="editable-field-edit"
        onClick={() => setEditing(true)}
        disabled={disabled}
        title="编辑"
      >
        编辑
      </button>
    </div>
  );
}
