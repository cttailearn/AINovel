import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { ConfirmDialog } from './Modal/ConfirmDialog.jsx';
import { useToast } from './Toast/ToastProvider.jsx';

const VARIABLE_TOKENS = ['{chunk_text}', '{character_list_json}', '{event_list_json}'];

function summarize(text, limit = 80) {
  if (!text) return '（空）';
  const single = text.replace(/\s+/g, ' ').trim();
  if (single.length <= limit) return single;
  return `${single.slice(0, limit)}…`;
}

function PromptListItem({ prompt, selected, onSelect, onToggle }) {
  return (
    <button
      type="button"
      className={`atelier-item ${selected ? 'selected' : ''} ${prompt.is_enabled ? '' : 'disabled'}`}
      onClick={() => onSelect(prompt.id)}
    >
      <div className="atelier-item-head">
        <h4 className="atelier-item-name" title={prompt.name}>
          {prompt.name}
        </h4>
        {prompt.is_builtin && <span className="atelier-pill">内置</span>}
      </div>
      <span className="atelier-item-key">{prompt.key}</span>
      {prompt.description && (
        <p className="atelier-item-desc">{prompt.description}</p>
      )}
      <div className="atelier-item-foot">
        <span>
          {prompt.is_enabled ? '已启用' : '已禁用'}
        </span>
        <button
          type="button"
          className={`toggle-btn ${prompt.is_enabled ? 'active' : ''}`}
          onClick={(e) => {
            e.stopPropagation();
            onToggle(prompt.id, prompt.is_enabled ? 0 : 1);
          }}
          title={prompt.is_enabled ? '禁用此提示词' : '启用此提示词'}
          aria-label={prompt.is_enabled ? '禁用' : '启用'}
        >
          <span className="toggle-indicator"></span>
        </button>
      </div>
    </button>
  );
}

function PromptEditor({ prompt, dirty, onChange, onSave, onReset, saving, resetting, deleting }) {
  const [form, setForm] = useState(() => ({
    name: prompt.name || '',
    description: prompt.description || '',
    system_prompt: prompt.system_prompt || '',
    user_prompt_template: prompt.user_prompt_template || '',
    temperature: prompt.temperature ?? 0.3,
    max_tokens: prompt.max_tokens ?? 2400,
    is_enabled: prompt.is_enabled !== false,
  }));

  useEffect(() => {
    setForm({
      name: prompt.name || '',
      description: prompt.description || '',
      system_prompt: prompt.system_prompt || '',
      user_prompt_template: prompt.user_prompt_template || '',
      temperature: prompt.temperature ?? 0.3,
      max_tokens: prompt.max_tokens ?? 2400,
      is_enabled: prompt.is_enabled !== false,
    });
  }, [prompt.id, prompt.updated_at]);

  const setField = (key, value) => {
    setForm((prev) => {
      const next = { ...prev, [key]: value };
      onChange?.(next);
      return next;
    });
  };

  const insertVariable = (token) => {
    setForm((prev) => ({
      ...prev,
      user_prompt_template: `${prev.user_prompt_template || ''}${token}`,
    }));
  };

  const saveable =
    form.name.trim().length > 0 && form.user_prompt_template.length > 0;

  return (
    <div className="prompt-editor">
      <div className="prompt-editor-head">
        <div className="prompt-editor-title">
          <span className="atelier-eyebrow">Prompt Template</span>
          <h2>{prompt.name || '提示词详情'}</h2>
          <span className="prompt-editor-key">{prompt.key}</span>
        </div>
        <div className="prompt-editor-meta">
          {prompt.is_builtin && <span className="atelier-pill">内置</span>}
          <span
            className={`status-dot ${form.is_enabled ? 'success' : 'error-dot'}`}
            title={form.is_enabled ? '已启用' : '已禁用'}
          />
          <span className="status-text">
            {form.is_enabled ? '已启用' : '已禁用'}
          </span>
        </div>
      </div>

      {prompt.description && (
        <p className="prompt-editor-desc">{prompt.description}</p>
      )}

      <div className="prompt-form-grid">
        <div className="form-group">
          <label>名称 *</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setField('name', e.target.value)}
            placeholder="提示词名称"
          />
        </div>
        <div className="form-group">
          <label>启用</label>
          <label className="switch">
            <input
              type="checkbox"
              checked={form.is_enabled}
              onChange={(e) => setField('is_enabled', e.target.checked)}
            />
            <span className="slider"></span>
          </label>
        </div>
      </div>

      <div className="form-group">
        <label>描述</label>
        <input
          type="text"
          value={form.description}
          onChange={(e) => setField('description', e.target.value)}
          placeholder="一句话说明该提示词的用途"
        />
      </div>

      <div className="form-group">
        <label>System Prompt</label>
        <textarea
          rows={5}
          value={form.system_prompt}
          onChange={(e) => setField('system_prompt', e.target.value)}
          placeholder="设置模型的角色与行为规范，可留空。"
        />
        <div className="char-count">{form.system_prompt.length} 字符</div>
      </div>

      <div className="form-group">
        <div className="prompt-editor-label-row">
          <label>User Prompt 模板 *</label>
          <div className="variable-insert">
            <span className="variable-hint">插入变量</span>
            {VARIABLE_TOKENS.map((tok) => (
              <button
                key={tok}
                type="button"
                className="variable-btn"
                onClick={() => insertVariable(tok)}
                title={`追加到末尾：${tok}`}
              >
                {tok}
              </button>
            ))}
          </div>
        </div>
        <textarea
          rows={14}
          value={form.user_prompt_template}
          onChange={(e) => setField('user_prompt_template', e.target.value)}
          placeholder="使用 {chunk_text}、{character_list_json} 等占位符。"
          className="prompt-textarea code"
        />
        <div className="char-count">{form.user_prompt_template.length} 字符</div>
      </div>

      <div className="prompt-form-grid">
        <div className="form-group">
          <label>Temperature</label>
          <input
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={form.temperature}
            onChange={(e) => setField('temperature', Number(e.target.value))}
          />
          <div className="form-hint">0 = 精确，2 = 创造性。默认 0.3。</div>
        </div>
        <div className="form-group">
          <label>Max Tokens</label>
          <input
            type="number"
            min="1"
            max="128000"
            step="100"
            value={form.max_tokens}
            onChange={(e) => setField('max_tokens', Number(e.target.value))}
          />
          <div className="form-hint">单次响应的最大 token 数。</div>
        </div>
      </div>

      <div className="prompt-editor-actions">
        {prompt.is_builtin && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onReset}
            disabled={saving || resetting}
            title="恢复为内置默认值"
          >
            {resetting ? '重置中…' : '恢复默认'}
          </button>
        )}
        {!prompt.is_builtin && (
          <button
            type="button"
            className="btn btn-ghost danger"
            onClick={deleting.onClick}
            disabled={saving || deleting.busy}
            title="删除自定义提示词"
          >
            {deleting.busy ? '删除中…' : '删除'}
          </button>
        )}
        <div className="prompt-editor-actions-spacer" />
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => onSave(form)}
          disabled={!saveable || !dirty || saving}
        >
          {saving ? '保存中…' : '保存修改'}
        </button>
      </div>
    </div>
  );
}

function CreatePromptDialog({ open, categories, onCancel, onCreate }) {
  const [form, setForm] = useState({
    name: '',
    key: '',
    category: 'kg',
    description: '',
    system_prompt: '',
    user_prompt_template: '{chunk_text}',
    temperature: 0.3,
    max_tokens: 2400,
    is_enabled: true,
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setForm({
        name: '',
        key: '',
        category: 'kg',
        description: '',
        system_prompt: '',
        user_prompt_template: '{chunk_text}',
        temperature: 0.3,
        max_tokens: 2400,
        is_enabled: true,
      });
    }
  }, [open]);

  if (!open) return null;

  const saveable = form.name.trim() && form.key.trim() && form.user_prompt_template.length;

  const handleSubmit = async () => {
    if (!saveable) return;
    setBusy(true);
    try {
      await onCreate(form);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div
        className="modal-panel prompt-create-modal prompt-editor"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="modal-title">新建提示词</h3>
        <p className="modal-message">
          自定义提示词仅在该提示词被代码显式引用时才会生效；建议先在文档或
          代码中确认键名。
        </p>

        <div className="form-group">
          <label>名称 *</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label>Key *</label>
          <input
            type="text"
            value={form.key}
            onChange={(e) => setForm({ ...form, key: e.target.value })}
            placeholder="例如 my_agent.rewrite"
          />
        </div>
        <div className="form-group">
          <label>分类 *</label>
          <select
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
          >
            {categories.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label>描述</label>
          <input
            type="text"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label>System Prompt</label>
          <textarea
            rows={3}
            value={form.system_prompt}
            onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label>User Prompt 模板 *</label>
          <textarea
            rows={6}
            value={form.user_prompt_template}
            onChange={(e) => setForm({ ...form, user_prompt_template: e.target.value })}
          />
        </div>
        <div className="prompt-form-grid">
          <div className="form-group">
            <label>Temperature</label>
            <input
              type="number"
              min="0"
              max="2"
              step="0.1"
              value={form.temperature}
              onChange={(e) => setForm({ ...form, temperature: Number(e.target.value) })}
            />
          </div>
          <div className="form-group">
            <label>Max Tokens</label>
            <input
              type="number"
              min="1"
              max="128000"
              step="100"
              value={form.max_tokens}
              onChange={(e) => setForm({ ...form, max_tokens: Number(e.target.value) })}
            />
          </div>
        </div>

        <div className="modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            取消
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={!saveable || busy}
          >
            {busy ? '创建中…' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function PromptManagerPanel() {
  const toast = useToast();
  const [prompts, setPrompts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [filterCategory, setFilterCategory] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [creating, setCreating] = useState(false);
  const dirtyRef = useRef(false);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const data = await api.prompts.list();
      setPrompts(data.prompts || []);
      setCategories(data.categories || []);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '加载提示词失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const visiblePrompts = useMemo(() => {
    let list = prompts;
    if (filterCategory !== 'all') {
      list = list.filter((p) => p.category === filterCategory);
    }
    if (searchTerm.trim()) {
      const term = searchTerm.trim().toLowerCase();
      list = list.filter(
        (p) =>
          (p.name || '').toLowerCase().includes(term) ||
          (p.key || '').toLowerCase().includes(term) ||
          (p.description || '').toLowerCase().includes(term)
      );
    }
    return list;
  }, [prompts, filterCategory, searchTerm]);

  useEffect(() => {
    if (visiblePrompts.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!visiblePrompts.find((p) => p.id === selectedId)) {
      setSelectedId(visiblePrompts[0].id);
    }
  }, [visiblePrompts, selectedId]);

  const selected = useMemo(
    () => prompts.find((p) => p.id === selectedId) || null,
    [prompts, selectedId]
  );

  const stats = useMemo(() => {
    const total = prompts.length;
    const enabled = prompts.filter((p) => p.is_enabled).length;
    const builtin = prompts.filter((p) => p.is_builtin).length;
    return { total, enabled, builtin };
  }, [prompts]);

  const handleSave = async (form) => {
    if (!selected) return;
    setSaving(true);
    try {
      await api.prompts.update(selected.id, {
        name: form.name,
        description: form.description,
        system_prompt: form.system_prompt,
        user_prompt_template: form.user_prompt_template,
        temperature: form.temperature,
        max_tokens: form.max_tokens,
        is_enabled: form.is_enabled,
      });
      toast.success('提示词已保存');
      dirtyRef.current = false;
      await fetchAll();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!selected) return;
    setResetting(true);
    try {
      await api.prompts.reset(selected.id);
      toast.success('已恢复为内置默认');
      dirtyRef.current = false;
      await fetchAll();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '重置失败');
    } finally {
      setResetting(false);
    }
  };

  const handleToggle = async (id, enabled) => {
    try {
      await api.prompts.update(id, { is_enabled: !!enabled });
      await fetchAll();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '操作失败');
    }
  };

  const handleCreate = async (payload) => {
    try {
      const created = await api.prompts.create(payload);
      toast.success('已创建');
      setCreating(false);
      await fetchAll();
      setSelectedId(created.id);
      setFilterCategory(created.category);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '创建失败');
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setPendingDelete(null);
    try {
      await api.prompts.remove(id);
      toast.success('已删除');
      await fetchAll();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  if (loading) {
    return (
      <div className="loading-block">
        <div className="loading-spinner large"></div>
        <p>加载提示词...</p>
      </div>
    );
  }

  return (
    <div className="atelier-shell">
      <aside className="atelier-aside">
        <header className="atelier-aside-head">
          <span className="atelier-eyebrow">Prompt Library</span>
          <h2 className="atelier-title">提示词</h2>
          <p className="atelier-lede">
            查看和自定义所有发送给大模型的提示词。点击列表项查看与编辑；列表右侧开关可即时启停。
          </p>
          <div className="atelier-meta-grid">
            <div className="atelier-meta-cell">
              <span className="atelier-meta-value">{stats.total}</span>
              <span className="atelier-meta-label">模板</span>
            </div>
            <div className="atelier-meta-cell">
              <span className="atelier-meta-value">{stats.enabled}</span>
              <span className="atelier-meta-label">启用</span>
            </div>
            <div className="atelier-meta-cell">
              <span className="atelier-meta-value">{stats.builtin}</span>
              <span className="atelier-meta-label">内置</span>
            </div>
          </div>
        </header>

        <div className="atelier-aside-tools">
          <label className="atelier-search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
              <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" />
            </svg>
            <select
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value)}
            >
              <option value="all">全部分类</option>
              {categories.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="atelier-search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M3 5h18M3 12h18M3 19h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="按键名、名称、描述搜索"
            />
          </label>
        </div>

        <div className="atelier-aside-list">
          {visiblePrompts.length === 0 ? (
            <div className="atelier-list-empty">
              {prompts.length === 0
                ? '尚无任何提示词模板。'
                : '没有匹配的提示词，请调整筛选条件。'}
            </div>
          ) : (
            visiblePrompts.map((p) => (
              <PromptListItem
                key={p.id}
                prompt={p}
                selected={p.id === selectedId}
                onSelect={setSelectedId}
                onToggle={handleToggle}
              />
            ))
          )}
        </div>
      </aside>

      <section className="atelier-main">
        <div className="atelier-main-head">
          <div className="atelier-main-head-left">
            <span className="atelier-eyebrow">Prompt Workspace</span>
            <h1 className="atelier-main-title">
              {selected ? selected.name : '提示词管理'}
            </h1>
            <p className="atelier-main-subtitle">
              {selected
                ? '编辑当前提示词的内容、行为参数与温度。保存后立即生效；内置模板可一键恢复默认。'
                : '从左侧选择一条提示词进行查看或编辑。'}
            </p>
          </div>
          <div className="atelier-main-head-right">
            <button
              type="button"
              className="new-config-btn"
              onClick={() => setCreating(true)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" />
              </svg>
              新建提示词
            </button>
          </div>
        </div>

        {selected ? (
          <div className="prompt-detail-card">
            <PromptEditor
              key={selected.id}
              prompt={selected}
              dirty={dirtyRef.current}
              onChange={() => {
                dirtyRef.current = true;
              }}
              onSave={handleSave}
              onReset={handleReset}
              saving={saving}
              resetting={resetting}
              deleting={{
                onClick: () => setPendingDelete(selected),
                busy: false,
              }}
            />
          </div>
        ) : (
          <div className="atelier-empty">
            <div className="atelier-empty-mark">词</div>
            <h3 className="atelier-empty-title">尚未选择任何提示词</h3>
            <p className="atelier-empty-msg">
              从左侧列表选中一条提示词以查看与编辑。
            </p>
          </div>
        )}

        <div className="prompt-category-overview">
          {categories.map((c) => {
            const count = prompts.filter((p) => p.category === c.key).length;
            return (
              <div className="prompt-category-card" key={c.key}>
                <div className="prompt-category-card-head">
                  <h3>{c.label}</h3>
                  <span className="config-count">{count}</span>
                </div>
                <p>{c.description}</p>
                <div className="prompt-category-tags">
                  {prompts
                    .filter((p) => p.category === c.key)
                    .slice(0, 4)
                    .map((p) => (
                      <span key={p.id} className="prompt-category-chip">
                        {summarize(p.name, 12)}
                      </span>
                    ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <CreatePromptDialog
        open={creating}
        categories={categories}
        onCancel={() => setCreating(false)}
        onCreate={handleCreate}
      />

      <ConfirmDialog
        open={!!pendingDelete}
        title="删除提示词"
        message={`确定要删除「${pendingDelete?.name || pendingDelete?.key}」吗？此操作不可撤销。`}
        danger
        confirmText="删除"
        onCancel={() => setPendingDelete(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}
