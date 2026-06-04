import { useEffect, useState } from 'react';
import { ApiError, api } from './api/client.js';
import { useToast } from './components/Toast/ToastProvider.jsx';
import { ModelConfigPanel } from './components/ModelConfigPanel.jsx';
import { PromptManagerPanel } from './components/PromptManagerPanel.jsx';
import { Workbench } from './components/Workbench.jsx';
import { KnowledgeGraphPage } from './components/KnowledgeGraphPage.jsx';
import { ImageGenerationPage } from './components/ImageGenerationPage.jsx';
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
      <span className="rail-btn-icon">
        {status === 'error' ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
            <circle cx="12" cy="12" r="10" stroke="currentColor" />
            <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" />
            <path d="M22 4L12 14.01l-3-3" stroke="currentColor" />
          </svg>
        )}
      </span>
      <span>{status === 'ok' ? '已连接' : status === 'error' ? '已断开' : '检查中'}</span>
    </button>
  );
}

const NAV_ITEMS = [
  {
    key: 'workbench',
    title: '工作台',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
        <path d="M3 7l9-4 9 4-9 4-9-4z" stroke="currentColor" strokeLinejoin="round" />
        <path d="M3 12l9 4 9-4M3 17l9 4 9-4" stroke="currentColor" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    key: 'knowledge',
    title: '知识图谱',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
        <circle cx="12" cy="12" r="3" stroke="currentColor" />
        <circle cx="4" cy="6" r="2" stroke="currentColor" />
        <circle cx="20" cy="6" r="2" stroke="currentColor" />
        <circle cx="4" cy="18" r="2" stroke="currentColor" />
        <circle cx="20" cy="18" r="2" stroke="currentColor" />
        <path d="M6 6l4 4M18 6l-4 4M6 18l4-4M18 18l-4-4" stroke="currentColor" />
      </svg>
    ),
  },
  {
    key: 'image',
    title: '图像生成',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
        <rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" />
        <circle cx="8.5" cy="9.5" r="1.5" stroke="currentColor" />
        <path d="M21 16l-5-5-7 7" stroke="currentColor" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    key: 'settings',
    title: '系统设置',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
        <circle cx="12" cy="12" r="3" stroke="currentColor" />
        <path
          d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06A2 2 0 113.39 16.96l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H2a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H8a1.65 1.65 0 001-1.51V2a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V8a1.65 1.65 0 001.51 1H22a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
];

const PAGE_META = {
  workbench: { title: '我的项目', sub: '管理并解析你的小说项目' },
  knowledge: { title: '知识图谱', sub: '查看人物、事件与关系' },
  image: { title: '图像生成', sub: '文生图 / 图生图，多模型、多风格' },
  settings: { title: '系统设置', sub: '配置模型与提示词' },
};

export default function App() {
  const { theme, toggleTheme } = useTheme();
  const toast = useToast();
  const [activeNav, setActiveNav] = useState('workbench');
  const [settingsTab, setSettingsTab] = useState('models');
  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [topSearch, setTopSearch] = useState('');

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

  useEffect(() => {
    setTopSearch('');
  }, [activeNav]);

  const meta = PAGE_META[activeNav] || PAGE_META.workbench;

  return (
    <div className="workbench-shell rail-shell">
      <aside className="rail-sidebar" aria-label="主导航">
        <div className="rail-brand" title="AI 小说">
          <span className="rail-brand-mark">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M5 4h11l3 3v13a1 1 0 01-1 1H5a1 1 0 01-1-1V5a1 1 0 011-1z" stroke="currentColor" strokeWidth="1.5" />
              <path d="M16 4v3h3" stroke="currentColor" strokeWidth="1.5" />
              <path d="M8 12h8M8 16h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </span>
          <span className="rail-brand-text">
            <span className="rail-brand-title">AI 小说</span>
            <span className="rail-brand-sub">智能写作助手</span>
          </span>
        </div>

        <nav className="rail-nav">
          <span className="rail-nav-label">导航</span>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`rail-btn ${activeNav === item.key ? 'active' : ''}`}
              onClick={() => setActiveNav(item.key)}
              title={item.title}
              aria-label={item.title}
            >
              <span className="rail-btn-icon">{item.icon}</span>
              <span>{item.title}</span>
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
            <span className="rail-btn-icon">
              {theme === 'dark' ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
                  <circle cx="12" cy="12" r="5" stroke="currentColor" />
                  <path
                    d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
                    stroke="currentColor"
                  />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
                  <path
                    d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"
                    stroke="currentColor"
                  />
                </svg>
              )}
            </span>
            <span>{theme === 'dark' ? '浅色' : '暗色'}</span>
          </button>
          <BackendStatus refreshAll={fetchModels} />
        </div>
      </aside>

      <main className="rail-main">
        <header className="rail-topbar">
          <div className="rail-topbar-title">
            <h1>{meta.title}</h1>
          </div>

          <div className="rail-topbar-search" role="search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" stroke="currentColor" />
              <path d="M21 21l-4.35-4.35" stroke="currentColor" />
            </svg>
            <input
              type="text"
              placeholder={
                activeNav === 'workbench'
                  ? '搜索项目标题、作者或内容...'
                  : activeNav === 'knowledge'
                    ? '搜索小说标题或作者...'
                    : activeNav === 'image'
                      ? '搜索结果...'
                      : '在设置中搜索...'
              }
              value={topSearch}
              onChange={(e) => setTopSearch(e.target.value)}
            />
          </div>

          <div className="rail-topbar-actions">
            <button
              type="button"
              className="rail-topbar-icon-btn"
              title="刷新"
              onClick={fetchModels}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
                <path d="M23 4v6h-6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M1 20v-6h6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </header>

        <section className="rail-body">
          {activeNav === 'workbench' ? (
            <Workbench models={models} topSearch={topSearch} />
          ) : activeNav === 'knowledge' ? (
            <KnowledgeGraphPage models={models} topSearch={topSearch} />
          ) : activeNav === 'image' ? (
            <ImageGenerationPage models={models} topSearch={topSearch} />
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
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
                    <rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" />
                    <path d="M8 9h8M8 13h5" stroke="currentColor" />
                  </svg>
                  模型配置
                </button>
                <button
                  type="button"
                  className={`settings-tab ${settingsTab === 'prompts' ? 'active' : ''}`}
                  onClick={() => setSettingsTab('prompts')}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
                    <path d="M4 5h16M4 12h16M4 19h10" stroke="currentColor" strokeLinecap="round" />
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
