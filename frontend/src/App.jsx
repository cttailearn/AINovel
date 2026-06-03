import { useEffect, useState } from 'react';
import { ApiError, api } from './api/client.js';
import { useToast } from './components/Toast/ToastProvider.jsx';
import { ModelConfigPanel } from './components/ModelConfigPanel.jsx';
import { PromptManagerPanel } from './components/PromptManagerPanel.jsx';
import { Workbench } from './components/Workbench.jsx';
import { KnowledgeGraphPage } from './components/KnowledgeGraphPage.jsx';
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
      className={`rail-btn ${status}`}
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

const NAV_ITEMS = [
  {
    key: 'workbench',
    title: '工作台',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <path d="M3 7l9-4 9 4-9 4-9-4z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <path d="M3 12l9 4 9-4M3 17l9 4 9-4" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    key: 'knowledge',
    title: '知识图谱',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
        <circle cx="4" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
        <circle cx="20" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
        <circle cx="4" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
        <circle cx="20" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
        <path d="M6 6l4 4M18 6l-4 4M6 18l4-4M18 18l-4-4" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
  },
  {
    key: 'settings',
    title: '系统设置',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
        <path
          d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06A2 2 0 113.39 16.96l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H2a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H8a1.65 1.65 0 001-1.51V2a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V8a1.65 1.65 0 001.51 1H22a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
];

export default function App() {
  const { theme, toggleTheme } = useTheme();
  const toast = useToast();
  const [activeNav, setActiveNav] = useState('workbench');
  const [settingsTab, setSettingsTab] = useState('models');
  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);

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

  useEffect(() => {
    fetchModels();
  }, []);

  return (
    <div className="workbench-shell rail-shell">
      <aside className="rail-sidebar" aria-label="主导航">
        <div className="rail-brand" title="AI 小说">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5z" fill="currentColor" />
            <path d="M2 17l10 5 10-5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M2 12l10 5 10-5" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </div>

        <nav className="rail-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`rail-btn ${activeNav === item.key ? 'active' : ''}`}
              onClick={() => setActiveNav(item.key)}
              title={item.title}
              aria-label={item.title}
            >
              {item.icon}
            </button>
          ))}
        </nav>

        <div className="rail-footer">
          <button
            type="button"
            className="rail-btn"
            onClick={toggleTheme}
            title={theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'}
          >
            {theme === 'dark' ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="5" stroke="currentColor" strokeWidth="2" />
                <path
                  d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
                  stroke="currentColor"
                  strokeWidth="2"
                />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path
                  d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"
                  stroke="currentColor"
                  strokeWidth="2"
                />
              </svg>
            )}
          </button>
          <BackendStatus refreshAll={fetchModels} />
        </div>
      </aside>

      <main className="rail-main">
        <section className="rail-body">
          {activeNav === 'workbench' ? (
            <Workbench models={models} />
          ) : activeNav === 'knowledge' ? (
            <KnowledgeGraphPage models={models} />
          ) : modelsLoading ? (
            <div className="loading-block">
              <div className="loading-spinner large"></div>
              <p>加载模型...</p>
            </div>
          ) : (
            <div className="settings-page">
              <div className="settings-tabs">
                <button
                  type="button"
                  className={`settings-tab ${settingsTab === 'models' ? 'active' : ''}`}
                  onClick={() => setSettingsTab('models')}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" strokeWidth="2" />
                    <path d="M8 9h8M8 13h5" stroke="currentColor" strokeWidth="2" />
                  </svg>
                  模型配置
                </button>
                <button
                  type="button"
                  className={`settings-tab ${settingsTab === 'prompts' ? 'active' : ''}`}
                  onClick={() => setSettingsTab('prompts')}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path d="M4 5h16M4 12h16M4 19h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  提示词管理
                </button>
              </div>
              {settingsTab === 'models' ? (
                <ModelConfigPanel configs={models} refetch={fetchModels} />
              ) : (
                <PromptManagerPanel />
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
