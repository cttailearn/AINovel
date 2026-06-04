import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { ConfirmDialog } from './Modal/ConfirmDialog.jsx';
import { useToast } from './Toast/ToastProvider.jsx';

const PROVIDER_OPTIONS = [
  { value: 'anthropic', label: 'Anthropic', icon: '🤖', description: 'Claude API' },
  { value: 'openai', label: 'OpenAI', icon: '🔮', description: 'ChatGPT API' },
  { value: 'custom', label: 'Custom', icon: '⚙️', description: 'Custom API' },
];

const CAPABILITY_OPTIONS = [
  {
    value: 'chat',
    label: '对话/文本',
    icon: '💬',
    description: '聊天/抽取/摘要等文本生成',
  },
  {
    value: 'image',
    label: '图像生成',
    icon: '🎨',
    description: '文生图、图生图（MiniMax 等）',
  },
];

// 图像生成模型：每个提供商有固定的 Base URL、协议和常用模型建议。
// 用户选择提供商、填入 API Key 与模型名称即可（模型名称可自由填写，
// 列表里的值仅作 datalist 自动补全建议）。
const IMAGE_PROVIDERS = [
  {
    value: 'minimax',
    label: 'MiniMax（海螺 AI）',
    icon: '🐶',
    baseUrl: 'https://api.minimaxi.com',
    models: ['image-01', 'image-01-live'],
    note: 'image-01 / image-01-live 均支持文生图与图生图。',
  },
  {
    value: 'dashscope',
    label: '阿里云百炼（DashScope）',
    icon: '☁️',
    baseUrl: 'https://dashscope.aliyuncs.com',
    models: ['qwen-image-2.0-pro', 'qwen-image-2.0'],
    note: 'qwen-image-2.0-pro 等多模态生图模型，支持多图参考。',
  },
];

function findImageProvider(provider, modelUrl) {
  if (!provider) return null;
  // First, match by stored provider value (e.g. "minimax").
  const direct = IMAGE_PROVIDERS.find((p) => p.value === provider);
  if (direct) return direct;
  // Fallback: match by base URL so configs created before this list still
  // resolve to the right provider.
  if (modelUrl) {
    const byUrl = IMAGE_PROVIDERS.find(
      (p) => p.baseUrl.replace(/\/+$/, '') === modelUrl.replace(/\/+$/, ''),
    );
    if (byUrl) return byUrl;
  }
  return null;
}

function ConfigList({ configs, selectedId, onSelect, onToggle, onDelete }) {
  return (
    <div className="config-list">
      <div className="config-list-header">
        <h3>模型列表</h3>
        <span className="config-count">{configs.length}</span>
      </div>
      <div className="config-list-items">
        {configs.length === 0 ? (
          <div className="empty-list">
            <p>暂无模型配置</p>
            <span>点击下方添加新模型开始配置</span>
          </div>
        ) : (
          configs.map((config) => {
            const isImage = (config.capability || 'chat') === 'image';
            const imageProv = isImage
              ? findImageProvider(config.provider, config.model_url)
              : null;
            const icon = isImage
              ? imageProv?.icon || '🎨'
              : PROVIDER_OPTIONS.find((p) => p.value === config.provider)?.icon || '⚙️';
            return (
              <div
                key={config.id}
                className={`config-list-item ${selectedId === config.id ? 'selected' : ''} ${config.enabled ? 'enabled' : 'disabled'}`}
                onClick={() => onSelect(config.id)}
              >
                <div className="config-item-main">
                  <span className="config-item-icon">{icon}</span>
                  <div className="config-item-info">
                    <span className="config-item-name">
                      {config.name || config.provider}
                      <span className={`capability-tag ${config.capability || 'chat'}`}>
                        {(config.capability || 'chat') === 'image' ? '图像' : '对话'}
                      </span>
                    </span>
                    <span className="config-item-model">
                      {isImage && imageProv
                        ? `${imageProv.label} · ${config.model_name}`
                        : config.model_name}
                    </span>
                  </div>
                </div>
                <div className="config-item-actions">
                  <button
                    className={`toggle-btn ${config.enabled ? 'active' : ''}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggle(config.id, config.enabled ? 0 : 1);
                    }}
                    title={config.enabled ? '禁用' : '启用'}
                  >
                    <span className="toggle-indicator"></span>
                  </button>
                  <button
                    className="delete-btn-small"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(config);
                    }}
                    title="删除"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"
                        stroke="currentColor"
                        strokeWidth="2"
                      />
                    </svg>
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function ConfigEditor({ config, onSave, onTest }) {
  const [formData, setFormData] = useState({
    name: '',
    provider: '',
    model_url: '',
    api_key: '',
    model_name: '',
    capability: 'chat',
    enabled: 1,
  });
  const [testStatus, setTestStatus] = useState(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  useEffect(() => {
    if (config) {
      const isImage = (config.capability || 'chat') === 'image';
      // For image configs, infer the provider from URL if the stored provider
      // doesn't match any known entry (legacy data).
      const providerValue = isImage
        ? (IMAGE_PROVIDERS.find((p) => p.value === config.provider)?.value ||
            IMAGE_PROVIDERS.find(
              (p) =>
                p.baseUrl.replace(/\/+$/, '') ===
                (config.model_url || '').replace(/\/+$/, ''),
            )?.value ||
            IMAGE_PROVIDERS[0].value)
        : config.provider || PROVIDER_OPTIONS[0].value;
      setFormData({
        id: config.id,
        name: config.name || '',
        provider: providerValue,
        model_url: config.model_url || '',
        api_key: config.api_key || '',
        model_name: config.model_name || '',
        capability: config.capability || 'chat',
        enabled: config.enabled ?? 1,
      });
    } else {
      setFormData({
        name: '',
        provider: PROVIDER_OPTIONS[0].value,
        model_url: '',
        api_key: '',
        model_name: '',
        capability: 'chat',
        enabled: 1,
      });
    }
    setTestStatus(null);
  }, [config]);

  const isImage = (formData.capability || 'chat') === 'image';
  const imageProvider = useMemo(
    () => (isImage ? findImageProvider(formData.provider, formData.model_url) : null),
    [isImage, formData.provider, formData.model_url],
  );
  const providerInfo = PROVIDER_OPTIONS.find((p) => p.value === formData.provider);
  const capabilityInfo =
    CAPABILITY_OPTIONS.find((c) => c.value === (formData.capability || 'chat')) ||
    CAPABILITY_OPTIONS[0];

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    setTestStatus(null);
  };

  const handleProviderSelect = (value) => {
    setFormData((prev) => ({ ...prev, provider: value }));
  };

  const handleCapabilitySelect = (value) => {
    setFormData((prev) => {
      // When switching capability, reset to a valid default for the new mode.
      if (value === 'image') {
        const p = IMAGE_PROVIDERS[0];
        return {
          ...prev,
          capability: 'image',
          provider: p.value,
          model_url: p.baseUrl,
          model_name: p.models[0],
        };
      }
      return {
        ...prev,
        capability: 'chat',
        provider: PROVIDER_OPTIONS[0].value,
      };
    });
    setTestStatus(null);
  };

  const handleImageProviderSelect = (value) => {
    const p = IMAGE_PROVIDERS.find((x) => x.value === value);
    if (!p) return;
    setFormData((prev) => ({
      ...prev,
      provider: p.value,
      model_url: p.baseUrl,
      // Keep the currently typed model if the new provider offers it as a
      // suggestion; otherwise fall back to the first suggestion in the list.
      model_name: p.models.includes(prev.model_name) ? prev.model_name : p.models[0],
    }));
    setTestStatus(null);
  };

  const handleImageModelChange = (value) => {
    setFormData((prev) => ({ ...prev, model_name: value }));
    setTestStatus(null);
  };

  const handleTest = async () => {
    if (!formData.model_url || !formData.api_key || !formData.model_name || !formData.provider) {
      setTestStatus({ success: false, message: '请填写所有必填项' });
      return;
    }
    setTesting(true);
    setTestStatus(null);
    try {
      // For image models, the backend uses the provider name to dispatch
      // (e.g. "minimax" -> /v1/image_generation, "dashscope" -> multimodal
      // generation). For chat models, the provider is the upstream protocol.
      const result = await api.models.test({
        provider: formData.provider,
        model_url: formData.model_url,
        api_key: formData.api_key,
        model_name: formData.model_name,
        capability: formData.capability || 'chat',
      });
      setTestStatus(result);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : '连接失败';
      setTestStatus({ success: false, message });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (!formData.name || !formData.provider || !formData.model_url || !formData.api_key || !formData.model_name) {
      toast.error('请填写所有必填项');
      return;
    }
    setSaving(true);
    try {
      await onSave(formData);
    } finally {
      setSaving(false);
    }
  };

  const isValid =
    formData.name && formData.provider && formData.model_url && formData.api_key && formData.model_name;

  return (
    <div
      className={`config-editor ${testStatus ? (testStatus.success ? 'success-card' : 'error-card') : ''}`}
    >
      <div className="editor-header">
        <div className="editor-title">
          <span className="provider-icon">{capabilityInfo.icon}</span>
          <div className="editor-title-text">
            <h2>{config ? formData.name || '编辑模型' : '新建模型'}</h2>
            <span className="editor-provider">{capabilityInfo.description}</span>
          </div>
        </div>
        {config && (
          <div className={`enabled-badge ${formData.enabled ? 'enabled' : 'disabled'}`}>
            <span className={`status-dot ${formData.enabled ? 'success' : 'error-dot'}`}></span>
            <span>{formData.enabled ? '已启用' : '已禁用'}</span>
          </div>
        )}
      </div>

      <div className="form-group">
        <label>配置名称 *</label>
        <input
          type="text"
          name="name"
          value={formData.name}
          onChange={handleChange}
          placeholder={isImage ? '我的 MiniMax 图像模型' : '我的 Claude API'}
        />
      </div>

      <div className="form-group">
        <label>能力类型 *</label>
        <div className="provider-selector">
          {CAPABILITY_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`provider-option ${(formData.capability || 'chat') === opt.value ? 'selected' : ''}`}
              onClick={() => handleCapabilitySelect(opt.value)}
            >
              <span className="provider-option-icon">{opt.icon}</span>
              <span className="provider-option-label">{opt.label}</span>
            </button>
          ))}
        </div>
        <span className="form-hint">
          {isImage
            ? '图像生成模型：选择提供商后，URL 与可用模型会自动填充，只需填入 API Key 即可。'
            : '对话/文本模型：用于聊天、知识图谱抽取、摘要等。'}
        </span>
      </div>

      {isImage ? (
        <>
          <div className="form-group">
            <label>模型提供商 *</label>
            <div className="provider-selector">
              {IMAGE_PROVIDERS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`provider-option ${formData.provider === opt.value ? 'selected' : ''}`}
                  onClick={() => handleImageProviderSelect(opt.value)}
                >
                  <span className="provider-option-icon">{opt.icon}</span>
                  <span className="provider-option-label">{opt.label}</span>
                </button>
              ))}
            </div>
            {imageProvider && (
              <span className="form-hint">
                接口地址：<code>{imageProvider.baseUrl}</code>
              </span>
            )}
          </div>

          <div className="form-group">
            <label>模型名称 *</label>
            <input
              type="text"
              name="model_name"
              value={formData.model_name}
              onChange={(e) => handleImageModelChange(e.target.value)}
              list={imageProvider ? `models-${imageProvider.value}` : undefined}
              placeholder={
                imageProvider?.models?.[0] || '例如：image-01'
              }
            />
            {imageProvider && (
              <datalist id={`models-${imageProvider.value}`}>
                {imageProvider.models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            )}
            <span className="form-hint">
              {imageProvider?.note ||
                '可选择下方建议或自行输入新模型名称。'}
            </span>
          </div>

          <div className="form-group">
            <label>API 密钥 *</label>
            <input
              type="password"
              name="api_key"
              value={formData.api_key}
              onChange={handleChange}
              placeholder="eyJ..."
            />
          </div>
        </>
      ) : (
        <>
          <div className="form-group">
            <label>提供商 *</label>
            <div className="provider-selector">
              {PROVIDER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`provider-option ${formData.provider === opt.value ? 'selected' : ''}`}
                  onClick={() => handleProviderSelect(opt.value)}
                >
                  <span className="provider-option-icon">{opt.icon}</span>
                  <span className="provider-option-label">{opt.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label>模型 URL *</label>
            <input
              type="text"
              name="model_url"
              value={formData.model_url}
              onChange={handleChange}
              placeholder="https://api.example.com/v1"
            />
          </div>

          <div className="form-group">
            <label>API 密钥 *</label>
            <input
              type="password"
              name="api_key"
              value={formData.api_key}
              onChange={handleChange}
              placeholder="sk-..."
            />
          </div>

          <div className="form-group">
            <label>模型名称 *</label>
            <input
              type="text"
              name="model_name"
              value={formData.model_name}
              onChange={handleChange}
              placeholder="gpt-4, claude-3-5-sonnet, 等"
            />
          </div>
        </>
      )}

      <div className="form-group toggle-group">
        <label>启用</label>
        <label className="switch">
          <input
            type="checkbox"
            checked={formData.enabled === 1}
            onChange={(e) => setFormData((prev) => ({ ...prev, enabled: e.target.checked ? 1 : 0 }))}
          />
          <span className="slider"></span>
        </label>
      </div>

      <div className="button-group">
        <button
          className={`test-button ${testing ? 'testing' : ''}`}
          onClick={handleTest}
          disabled={testing || !isValid}
        >
          {testing ? (
            <span className="loading-spinner"></span>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2" />
              <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2" />
            </svg>
          )}
          测试连接
        </button>

        <button
          className={`save-button ${saving ? 'saving' : ''}`}
          onClick={handleSave}
          disabled={saving || !isValid}
        >
          {saving ? (
            <span className="loading-spinner"></span>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path
                d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"
                stroke="currentColor"
                strokeWidth="2"
              />
              <path d="M17 21v-8H7v8M7 3v5h8" stroke="currentColor" strokeWidth="2" />
            </svg>
          )}
          {config ? '更新' : '保存'}
        </button>
      </div>

      {testStatus && (
        <div className={`status-message ${testStatus.success ? 'success-message' : 'error-message'}`}>
          {testStatus.success ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2" />
              <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2" />
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
              <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="2" />
            </svg>
          )}
          <span>{testStatus.message}</span>
          {testStatus.response_time && (
            <span className="response-time">{testStatus.response_time}秒</span>
          )}
        </div>
      )}
    </div>
  );
}

export function ModelConfigPanel({ configs, refetch }) {
  const toast = useToast();
  const [selectedId, setSelectedId] = useState(null);
  const [creatingNew, setCreatingNew] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  useEffect(() => {
    if (configs.length > 0 && !selectedId && !creatingNew) {
      setSelectedId(configs[0].id);
    }
  }, [configs, selectedId, creatingNew]);

  const selectedConfig = configs.find((c) => c.id === selectedId) || null;

  const handleSave = async (formData) => {
    try {
      if (formData.id) {
        await api.models.update(formData.id, formData);
        toast.success('模型已更新');
      } else {
        await api.models.create(formData);
        toast.success('模型已创建');
      }
      setCreatingNew(false);
      await refetch();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '保存失败');
    }
  };

  const handleToggle = async (id, enabled) => {
    try {
      await api.models.toggle(id, enabled);
      await refetch();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '操作失败');
    }
  };

  const handleDelete = async (config) => {
    setPendingDelete(config);
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setPendingDelete(null);
    try {
      await api.models.remove(id);
      toast.success('已删除');
      if (selectedId === id) {
        setSelectedId(null);
        setCreatingNew(true);
      }
      await refetch();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  const handleNew = () => {
    setSelectedId(null);
    setCreatingNew(true);
  };

  return (
    <div className="settings-content">
      <ConfigList
        configs={configs}
        selectedId={selectedId}
        onSelect={(id) => {
          setSelectedId(id);
          setCreatingNew(false);
        }}
        onToggle={handleToggle}
        onDelete={handleDelete}
      />
      <div className="editor-panel">
        <ConfigEditor
          key={creatingNew ? 'new' : selectedConfig ? selectedConfig.id : 'empty'}
          config={creatingNew ? null : selectedConfig}
          onSave={handleSave}
          onTest={() => {}}
        />
        <button className="new-config-btn" onClick={handleNew}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" />
          </svg>
          添加新模型
        </button>
      </div>
      <ConfirmDialog
        open={!!pendingDelete}
        title="删除模型"
        message={`确定要删除「${pendingDelete?.name || pendingDelete?.provider}」吗？此操作不可撤销。`}
        danger
        confirmText="删除"
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
