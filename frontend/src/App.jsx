import { useState, useEffect } from 'react';
import { getBackendUrl, useApiRequest } from './config.js';
import './App.css';

const PROVIDER_OPTIONS = [
  { value: 'anthropic', label: 'Anthropic', icon: '🤖', description: 'Claude API' },
  { value: 'openai', label: 'OpenAI', icon: '🔮', description: 'ChatGPT API' },
  { value: 'custom', label: 'Custom', icon: '⚙️', description: 'Custom API' }
];

function ConfigList({ configs, selectedId, onSelect, onToggle, onDelete }) {
  return (
    <div className="config-list">
      <div className="config-list-header">
        <h3>Models</h3>
        <span className="config-count">{configs.length}</span>
      </div>
      <div className="config-list-items">
        {configs.length === 0 ? (
          <div className="empty-list">
            <p>No models configured</p>
            <span>Add a new model to get started</span>
          </div>
        ) : (
          configs.map(config => (
            <div
              key={config.id}
              className={`config-list-item ${selectedId === config.id ? 'selected' : ''} ${config.enabled ? 'enabled' : 'disabled'}`}
              onClick={() => onSelect(config.id)}
            >
              <div className="config-item-main">
                <span className="config-item-icon">
                  {PROVIDER_OPTIONS.find(p => p.value === config.provider)?.icon || '⚙️'}
                </span>
                <div className="config-item-info">
                  <span className="config-item-name">{config.name || config.provider}</span>
                  <span className="config-item-model">{config.model_name}</span>
                </div>
              </div>
              <div className="config-item-actions">
                <button
                  className={`toggle-btn ${config.enabled ? 'active' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggle(config.id, config.enabled ? 0 : 1);
                  }}
                  title={config.enabled ? 'Disable' : 'Enable'}
                >
                  <span className="toggle-indicator"></span>
                </button>
                <button
                  className="delete-btn-small"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm(`Delete "${config.name || config.provider}"?`)) {
                      onDelete(config.id);
                    }
                  }}
                  title="Delete"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" stroke="currentColor" strokeWidth="2"/>
                  </svg>
                </button>
              </div>
            </div>
          ))
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
    enabled: 1
  });
  const [testStatus, setTestStatus] = useState(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config) {
      setFormData({
        id: config.id,
        name: config.name || '',
        provider: config.provider || '',
        model_url: config.model_url || '',
        api_key: config.api_key || '',
        model_name: config.model_name || '',
        enabled: config.enabled ?? 1
      });
    } else {
      setFormData({
        name: '',
        provider: '',
        model_url: '',
        api_key: '',
        model_name: '',
        enabled: 1
      });
    }
    setTestStatus(null);
  }, [config]);

  const providerInfo = PROVIDER_OPTIONS.find(p => p.value === formData.provider) || PROVIDER_OPTIONS[2];

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
    setTestStatus(null);
  };

  const handleProviderSelect = (value) => {
    setFormData(prev => ({
      ...prev,
      provider: value
    }));
  };

  const handleTest = async () => {
    if (!formData.model_url || !formData.api_key || !formData.model_name || !formData.provider) {
      setTestStatus({ success: false, message: 'Please fill in all required fields' });
      return;
    }
    
    setTesting(true);
    setTestStatus(null);
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/models/test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          provider: formData.provider,
          model_url: formData.model_url,
          api_key: formData.api_key,
          model_name: formData.model_name
        }),
      });
      const result = await response.json();
      setTestStatus(result);
    } catch (err) {
      setTestStatus({ success: false, message: err.message });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (!formData.name || !formData.provider || !formData.model_url || !formData.api_key || !formData.model_name) {
      return;
    }
    
    setSaving(true);
    await onSave(formData, () => setSaving(false));
  };

  const isValid = formData.name && formData.provider && formData.model_url && formData.api_key && formData.model_name;

  return (
    <div className={`config-editor ${testStatus ? (testStatus.success ? 'success-card' : 'error-card') : ''}`}>
      <div className="editor-header">
        <div className="editor-title">
          <span className="provider-icon">{providerInfo.icon}</span>
          <div className="editor-title-text">
            <h2>{config ? (formData.name || 'Edit Model') : 'New Model'}</h2>
            <span className="editor-provider">{providerInfo.description}</span>
          </div>
        </div>
        {config && (
          <div className={`enabled-badge ${formData.enabled ? 'enabled' : 'disabled'}`}>
            <span className={`status-dot ${formData.enabled ? 'success' : 'error-dot'}`}></span>
            <span>{formData.enabled ? 'Enabled' : 'Disabled'}</span>
          </div>
        )}
      </div>
      
      <div className="form-group">
        <label>Configuration Name *</label>
        <input
          type="text"
          name="name"
          value={formData.name}
          onChange={handleChange}
          placeholder="My Claude API"
        />
      </div>

      <div className="form-group">
        <label>Provider *</label>
        <div className="provider-selector">
          {PROVIDER_OPTIONS.map(opt => (
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
        <label>Model URL *</label>
        <input
          type="text"
          name="model_url"
          value={formData.model_url}
          onChange={handleChange}
          placeholder="https://api.example.com/v1"
        />
      </div>

      <div className="form-group">
        <label>API Key *</label>
        <input
          type="password"
          name="api_key"
          value={formData.api_key}
          onChange={handleChange}
          placeholder="sk-..."
        />
      </div>

      <div className="form-group">
        <label>Model Name *</label>
        <input
          type="text"
          name="model_name"
          value={formData.model_name}
          onChange={handleChange}
          placeholder="gpt-4, claude-3-5-sonnet, etc."
        />
      </div>

      <div className="form-group toggle-group">
        <label>Enabled</label>
        <label className="switch">
          <input
            type="checkbox"
            checked={formData.enabled === 1}
            onChange={(e) => setFormData(prev => ({ ...prev, enabled: e.target.checked ? 1 : 0 }))}
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
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2"/>
              <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
          Test Connection
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
              <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z" stroke="currentColor" strokeWidth="2"/>
              <path d="M17 21v-8H7v8M7 3v5h8" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
          {config ? 'Update' : 'Save'}
        </button>
      </div>

      {testStatus && (
        <div className={`status-message ${testStatus.success ? 'success-message' : 'error-message'}`}>
          {testStatus.success ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2"/>
              <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2"/>
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2"/>
              <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
          <span>{testStatus.message}</span>
          {testStatus.response_time && (
            <span className="response-time">{testStatus.response_time}s</span>
          )}
        </div>
      )}
    </div>
  );
}

function App() {
  const { data: healthData, loading, error, refetch } = useApiRequest('/health');
  const { data: configsData, refetch: refetchConfigs } = useApiRequest('/models');

  const [selectedConfigId, setSelectedConfigId] = useState(null);
  const configs = configsData?.configs || [];
  const selectedConfig = configs.find(c => c.id === selectedConfigId);

  useEffect(() => {
    if (configs.length > 0 && !selectedConfigId) {
      setSelectedConfigId(configs[0].id);
    }
  }, [configs]);

  const handleSave = async (formData, setSaving) => {
    try {
      const API_BASE = getBackendUrl();
      const method = formData.id ? 'PUT' : 'POST';
      const url = formData.id 
        ? `${API_BASE}/api/models/${formData.id}` 
        : `${API_BASE}/api/models`;
      
      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });
      
      if (response.ok) {
        const result = await response.json();
        await refetchConfigs();
      }
    } catch (err) {
      console.error('Save error:', err);
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (id, enabled) => {
    try {
      const API_BASE = getBackendUrl();
      await fetch(`${API_BASE}/api/models/${id}/toggle?enabled=${enabled}`, {
        method: 'PATCH',
      });
      await refetchConfigs();
    } catch (err) {
      console.error('Toggle error:', err);
    }
  };

  const handleDelete = async (id) => {
    try {
      const API_BASE = getBackendUrl();
      await fetch(`${API_BASE}/api/models/${id}`, {
        method: 'DELETE',
      });
      if (selectedConfigId === id) {
        setSelectedConfigId(null);
      }
      await refetchConfigs();
    } catch (err) {
      console.error('Delete error:', err);
    }
  };

  const handleNewConfig = () => {
    setSelectedConfigId(null);
  };

  return (
    <div className="app-container">
      <div className="hero-section">
        <div className="logo-badge">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5z" fill="#6366f1"/>
            <path d="M2 17l10 5 10-5" stroke="#818cf8" strokeWidth="2"/>
            <path d="M2 12l10 5 10-5" stroke="#a5b4fc" strokeWidth="2"/>
          </svg>
        </div>
        <h1 className="app-title">Settings</h1>
        <p className="app-subtitle">Manage your AI model configurations</p>
      </div>

      <div className="settings-content">
        <ConfigList
          configs={configs}
          selectedId={selectedConfigId}
          onSelect={setSelectedConfigId}
          onToggle={handleToggle}
          onDelete={handleDelete}
        />
        
        <div className="editor-panel">
          {selectedConfigId === null ? (
            <ConfigEditor
              config={null}
              onSave={handleSave}
              onTest={() => {}}
            />
          ) : selectedConfig ? (
            <ConfigEditor
              key={selectedConfig.id}
              config={selectedConfig}
              onSave={handleSave}
              onTest={() => {}}
            />
          ) : (
            <ConfigEditor
              config={null}
              onSave={handleSave}
              onTest={() => {}}
            />
          )}
          
          <button className="new-config-btn" onClick={handleNewConfig}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2"/>
            </svg>
            Add New Model
          </button>
        </div>
      </div>

      <div className="card status-card">
        <div className="card-header">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" stroke="#6366f1" strokeWidth="2"/>
          </svg>
          <h2>Backend Status</h2>
        </div>
        <div className="status-indicator">
          <div className={`status-dot ${loading ? 'pulse' : error ? 'error-dot' : 'success'}`}></div>
          <span className="status-text">
            {loading ? 'Checking...' : error ? 'Disconnected' : 'Connected'}
          </span>
        </div>
        {error && (
          <div className="error-message">
            <span>{error}</span>
          </div>
        )}
        <button className="refresh-button" onClick={() => { refetch(); refetchConfigs(); }} disabled={loading}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M23 4v6h-6M1 20v-6h6" stroke="currentColor" strokeWidth="2"/>
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" stroke="currentColor" strokeWidth="2"/>
          </svg>
          Refresh
        </button>
      </div>

      <div className="footer">
        <p>Last updated: {new Date().toLocaleTimeString()}</p>
        <p className="version">Frontend v1.0.0</p>
      </div>
    </div>
  );
}

export default App;