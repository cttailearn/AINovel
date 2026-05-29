import { useState, useEffect } from 'react';
import { getBackendUrl, useApiRequest } from './config.js';
import './App.css';

function SettingsCard({ provider, config, onSave, onTest }) {
  const [formData, setFormData] = useState({
    model_url: '',
    api_key: '',
    model_name: ''
  });
  const [testStatus, setTestStatus] = useState(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config) {
      setFormData({
        model_url: config.model_url || '',
        api_key: config.api_key || '',
        model_name: config.model_name || ''
      });
    }
  }, [config]);

  const handleChange = (e) => {
    setFormData(prev => ({
      ...prev,
      [e.target.name]: e.target.value
    }));
    setTestStatus(null);
  };

  const handleTest = async () => {
    if (!formData.model_url || !formData.api_key || !formData.model_name) {
      setTestStatus({ success: false, message: 'Please fill in all fields' });
      return;
    }
    
    setTesting(true);
    setTestStatus(null);
    await onTest(provider, formData, setTestStatus, setTesting);
  };

  const handleSave = async () => {
    if (!formData.model_url || !formData.api_key || !formData.model_name) {
      return;
    }
    
    setSaving(true);
    await onSave(provider, formData, setSaving);
  };

  const providerInfo = {
    anthropic: {
      name: 'Anthropic',
      icon: '🤖',
      description: 'Claude API compatible'
    },
    openai: {
      name: 'OpenAI',
      icon: '🔮',
      description: 'ChatGPT API compatible'
    }
  };

  const info = providerInfo[provider];

  return (
    <div className={`card settings-card ${testStatus ? (testStatus.success ? 'success-card' : 'error-card') : ''}`}>
      <div className="card-header">
        <span className="provider-icon">{info.icon}</span>
        <h2>{info.name}</h2>
        <span className="provider-badge">{info.description}</span>
      </div>
      
      <div className="form-group">
        <label>Model URL</label>
        <input
          type="text"
          name="model_url"
          value={formData.model_url}
          onChange={handleChange}
          placeholder={provider === 'anthropic' ? 'https://api.anthropic.com' : 'https://api.openai.com'}
        />
      </div>

      <div className="form-group">
        <label>API Key</label>
        <input
          type="password"
          name="api_key"
          value={formData.api_key}
          onChange={handleChange}
          placeholder="sk-..."
        />
      </div>

      <div className="form-group">
        <label>Model Name</label>
        <input
          type="text"
          name="model_name"
          value={formData.model_name}
          onChange={handleChange}
          placeholder={provider === 'anthropic' ? 'claude-3-5-sonnet' : 'gpt-4o'}
        />
      </div>

      <div className="button-group">
        <button 
          className={`test-button ${testing ? 'testing' : ''}`} 
          onClick={handleTest}
          disabled={testing}
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
          disabled={saving || !formData.model_url || !formData.api_key || !formData.model_name}
        >
          {saving ? (
            <span className="loading-spinner"></span>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z" stroke="currentColor" strokeWidth="2"/>
              <path d="M17 21v-8H7v8M7 3v5h8" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
          Save
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
  const [manualRefresh, setManualRefresh] = useState(0);
  const { data: healthData, loading, error, refetch } = useApiRequest('/health');
  const { data: configsData, refetch: refetchConfigs } = useApiRequest('/models');

  useEffect(() => {
    const timer = setTimeout(() => {
      setManualRefresh(prev => prev + 1);
    }, 5000);
    return () => clearTimeout(timer);
  }, [healthData]);

  const handleRefresh = () => {
    refetch();
    setManualRefresh(prev => prev + 1);
  };

  const handleTest = async (provider, formData, setTestStatus, setTesting) => {
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/models/test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          provider,
          ...formData
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

  const handleSave = async (provider, formData, setSaving) => {
    try {
      const API_BASE = getBackendUrl();
      await fetch(`${API_BASE}/api/models`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          provider,
          ...formData
        }),
      });
      await refetchConfigs();
    } catch (err) {
      console.error('Save error:', err);
    } finally {
      setSaving(false);
    }
  };

  const configs = configsData?.configs || [];
  const anthropicConfig = configs.find(c => c.provider === 'anthropic');
  const openaiConfig = configs.find(c => c.provider === 'openai');

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
        <h1 className="app-title">Model Settings</h1>
        <p className="app-subtitle">Configure your AI model connections</p>
      </div>

      <div className="dashboard-grid settings-grid">
        <SettingsCard
          provider="anthropic"
          config={anthropicConfig}
          onSave={handleSave}
          onTest={handleTest}
        />
        
        <SettingsCard
          provider="openai"
          config={openaiConfig}
          onSave={handleSave}
          onTest={handleTest}
        />
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
        <button className="refresh-button" onClick={handleRefresh} disabled={loading}>
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