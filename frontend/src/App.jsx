import { useEffect, useState } from 'react';
import { ApiError, api } from './api/client.js';
import { useToast } from './components/Toast/ToastProvider.jsx';
import { ModelConfigPanel } from './components/ModelConfigPanel.jsx';
import { NovelPanel } from './components/NovelPanel.jsx';
import { useTheme } from './ThemeContext.jsx';
import './App.css';

function BackendStatus({ refreshAll }) {
  const [status, setStatus] = useState('loading');
  const check = async () => {
    setStatus('loading');
    try {
      await api.health();
      setStatus('ok');
    } catch {
      setStatus('error');
    }
  };
  useEffect(() => {
    check();
  }, []);
  return (
    <button
      type="button"
      className={`status-icon ${status}`}
      onClick={() => {
        check();
        refreshAll?.();
      }}
      title={
        status === 'loading'
          ? '检查中...'
          : status === 'ok'
            ? '后端已连接'
            : '后端已断开'
      }
    >
      {status === 'error' ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
          <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="2" />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2" />
          <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2" />
        </svg>
      )}
    </button>
  );
}

export default function App() {
  const { theme, toggleTheme } = useTheme();
  const toast = useToast();
  const [activeTab, setActiveTab] = useState('models');
  const [models, setModels] = useState([]);
  const [novels, setNovels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [novelsLoading, setNovelsLoading] = useState(true);

  const fetchModels = async () => {
    setModelsLoading(true);
    try {
      const data = await api.models.list();
      setModels(data.configs || []);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '加载模型失败');
    } finally {
      setModelsLoading(false);
    }
  };

  const fetchNovels = async () => {
    setNovelsLoading(true);
    try {
      const data = await api.novels.list();
      setNovels(data.novels || []);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '加载小说失败');
    } finally {
      setNovelsLoading(false);
    }
  };

  useEffect(() => {
    fetchModels();
    fetchNovels();
  }, []);

  return (
    <div className="app-container">
      <div className="header-actions">
        <button
          className="theme-toggle"
          type="button"
          onClick={toggleTheme}
          title={theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'}
        >
          {theme === 'dark' ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="5" stroke="currentColor" strokeWidth="2" />
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" stroke="currentColor" strokeWidth="2" />
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" stroke="currentColor" strokeWidth="2" />
            </svg>
          )}
        </button>
        <BackendStatus refreshAll={() => { fetchModels(); fetchNovels(); }} />
      </div>

      <div className="hero-section">
        <div className="logo-badge">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5z" fill="#6366f1" />
            <path d="M2 17l10 5 10-5" stroke="#818cf8" strokeWidth="2" />
            <path d="M2 12l10 5 10-5" stroke="#a5b4fc" strokeWidth="2" />
          </svg>
        </div>
        <h1 className="app-title">AI 助手</h1>
        <p className="app-subtitle">管理您的 AI 模型与小说库</p>
      </div>

      <div className="tab-navigation">
        <button
          type="button"
          className={`tab-btn ${activeTab === 'models' ? 'active' : ''}`}
          onClick={() => setActiveTab('models')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" strokeWidth="2" />
            <path d="M2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" />
          </svg>
          模型配置
          {models.length > 0 && <span className="tab-badge">{models.length}</span>}
        </button>
        <button
          type="button"
          className={`tab-btn ${activeTab === 'novels' ? 'active' : ''}`}
          onClick={() => setActiveTab('novels')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="2" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="2" />
          </svg>
          小说管理
          {novels.length > 0 && <span className="tab-badge">{novels.length}</span>}
        </button>
      </div>

      {activeTab === 'models' ? (
        modelsLoading ? (
          <div className="loading-block">
            <div className="loading-spinner large"></div>
            <p>加载模型...</p>
          </div>
        ) : (
          <ModelConfigPanel configs={models} refetch={fetchModels} />
        )
      ) : novelsLoading ? (
        <div className="loading-block">
          <div className="loading-spinner large"></div>
          <p>加载小说...</p>
        </div>
      ) : (
        <NovelPanel novels={novels} refetch={fetchNovels} />
      )}

      <div className="footer">
        <p>最后更新: {new Date().toLocaleTimeString()}</p>
        <p className="version">前端版本 v1.2.0</p>
      </div>
    </div>
  );
}
