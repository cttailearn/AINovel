import { useCallback, useEffect, useMemo, useState } from 'react';
import { NavLink, useSearchParams } from 'react-router-dom';
import { ApiError, api } from './api/client.js';
import { useToast } from './components/Toast/ToastProvider.jsx';
import { ModelConfigPanel } from './components/ModelConfigPanel.jsx';
import { PromptManagerPanel } from './components/PromptManagerPanel.jsx';
import { Workbench } from './components/Workbench.jsx';
import { ImageGenerationPage } from './components/ImageGenerationPage.jsx';
import { EnrichmentTaskBanner } from './components/EnrichmentTaskBanner.jsx';
import { EnrichmentTaskProvider, useEnrichmentTask } from './state/EnrichmentTaskContext.jsx';
import { CreationTaskProvider } from './state/CreationTaskContext.jsx';
import { CreationStudio } from './components/creation/CreationStudio.jsx';
import { ConfirmProvider } from './hooks/ConfirmProvider.jsx';
import { ConnectionProvider, useConnection } from './state/ConnectionContext.jsx';
import { useTheme } from './ThemeContext.jsx';
import { ErrorBoundary } from './components/ErrorBoundary.jsx';
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
    title: '我的项目',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
        <path d="M3 7l9-4 9 4-9 4-9-4z" stroke="currentColor" strokeLinejoin="round" />
        <path d="M3 12l9 4 9-4M3 17l9 4 9-4" stroke="currentColor" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    key: 'creation',
    title: 'AI 小说创作',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
        <path d="M12 19l7-7 3 3-7 7-3-3z" stroke="currentColor" strokeLinejoin="round" />
        <path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z" stroke="currentColor" strokeLinejoin="round" />
        <path d="M2 2l7.586 7.586" stroke="currentColor" />
        <circle cx="11" cy="11" r="2" stroke="currentColor" />
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
  workbench: { title: '我的项目', sub: '管理、解析、阅读、加料、知识图谱 — 一站式工作台' },
  creation: { title: 'AI 小说创作', sub: '三 Agent 协作 · 三选一 · 知识图谱记忆 — 从零逐章生成' },
  image: { title: '图像生成', sub: '文生图 / 图生图，多模型、多风格' },
  settings: { title: '系统设置', sub: '配置模型与提示词' },
};

export default function App() {
  return (
    <EnrichmentTaskProvider>
      <CreationTaskProvider>
        <ConnectionProvider>
          <ConfirmProvider>
            <AppShell />
          </ConfirmProvider>
        </ConnectionProvider>
      </CreationTaskProvider>
    </EnrichmentTaskProvider>
  );
}

function AppShell() {
  const { theme, toggleTheme } = useTheme();
  const toast = useToast();
  const { reset: resetEnrichmentTask } = useEnrichmentTask();
  const conn = useConnection();
  const [searchParams, setSearchParams] = useSearchParams();
  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  // 子页面 (创作工作区) 可通过此回调更新顶栏标题: 进入某个项目时把它
  // 设置为 { parent, title }, 离开项目时传 null. 让顶栏出现面包屑,
  // 明确表达"我现在处于 AI 小说创作 → 某个项目"的层级关系.
  const [headerContext, setHeaderContext] = useState(null);
  const activeNav = searchParams.get('page') || 'workbench';
  const settingsTab = searchParams.get('tab') || 'models';
  const routeProjectId = Number(searchParams.get('project') || '') || null;
  const importNovelId = Number(searchParams.get('importNovel') || '') || null;

  const updateRoute = useCallback((patch) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([key, value]) => {
      if (value == null || value === '') next.delete(key);
      else next.set(key, String(value));
    });
    const page = next.get('page') || 'workbench';
    if (page !== 'settings') next.delete('tab');
    if (page !== 'creation') {
      next.delete('project');
      next.delete('importNovel');
    }
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const navHref = useCallback((page) => {
    const next = new URLSearchParams(searchParams);
    next.set('page', page);
    if (page !== 'settings') next.delete('tab');
    if (page !== 'creation') {
      next.delete('project');
      next.delete('importNovel');
    }
    return `/?${next.toString()}`;
  }, [searchParams]);

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

  const meta = PAGE_META[activeNav] || PAGE_META.workbench;
  const creationProps = useMemo(() => ({
    routeProjectId,
    importNovelId,
  }), [importNovelId, routeProjectId]);

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
            <NavLink
              key={item.key}
              to={navHref(item.key)}
              className={`rail-btn ${activeNav === item.key ? 'active' : ''}`}
              title={item.title}
              aria-label={item.title}
            >
              <span className="rail-btn-icon">{item.icon}</span>
              <span>{item.title}</span>
            </NavLink>
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
        {/* UX-#10: 后端断开全局 banner + 写操作拦截 */}
        {conn.status === 'error' && (
          <div className="connection-error-banner" role="alert">
            <span className="connection-error-banner-icon">⚠</span>
            <span className="connection-error-banner-msg">
              <strong>后端连接已断开</strong>
              {conn.retryIn > 0 && <> · {conn.retryIn}s 后自动重试</>}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => conn.check()}
              title="立即重试连接"
            >
              ↻ 重试
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => conn.ignoreOnce()}
              title="本会话忽略, 写操作会因连接失败而报错"
            >
              忽略
            </button>
          </div>
        )}
        <header className="rail-topbar">
          <div className="rail-topbar-title">
            {headerContext?.parent && headerContext?.title ? (
              // 进入创作项目时: 把顶栏标题改成面包屑, 表达层级关系
              <nav className="rail-topbar-breadcrumb" aria-label="路径导航">
                <button
                  type="button"
                  className="rail-topbar-crumb-link"
                  onClick={() => {
                    // 回到创作的项目列表 (而不是切到别的页面)
                    updateRoute({ page: 'creation', project: null });
                  }}
                  title={`返回 ${headerContext.parent}`}
                >
                  {headerContext.parent}
                </button>
                <span className="rail-topbar-crumb-sep" aria-hidden="true">/</span>
                <h1 className="rail-topbar-crumb-current">{headerContext.title}</h1>
              </nav>
            ) : (
              <h1>{meta.title}</h1>
            )}
          </div>

          <div className="rail-topbar-search" role="search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" stroke="currentColor" />
              <path d="M21 21l-4.35-4.35" stroke="currentColor" />
            </svg>
            {/* 修复 #32: 全局搜索框占位, 但实际搜索由各页面内部实现. 这里仅作为视觉占位. */}
            <input
              type="text"
              placeholder="搜索 (由当前页面处理)"
              disabled
              aria-label="页面级搜索"
            />
          </div>

          <div className="rail-topbar-actions">
            <EnrichmentTaskBanner
              onJumpToWorkbench={() => {
                resetEnrichmentTask();
                updateRoute({ page: 'workbench' });
              }}
            />
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

        <section className={`rail-body${activeNav === 'creation' ? ' rail-body-creation' : ''}`}>
          {activeNav === 'workbench' ? (
            <ErrorBoundary scope="我的项目" fallbackTitle="我的项目加载失败">
              <Workbench
                models={models}
                onBridgeToCreation={(novelId) => {
                  updateRoute({
                    page: 'creation',
                    project: null,
                    importNovel: novelId,
                  });
                }}
                onGoToSettings={() => {
                  updateRoute({ page: 'settings', tab: 'models' });
                }}
              />
            </ErrorBoundary>
          ) : activeNav === 'creation' ? (
            <ErrorBoundary scope="AI 小说创作" fallbackTitle="AI 创作加载失败">
              <CreationStudio
                models={models}
                {...creationProps}
                onImportNovelHandled={() => updateRoute({ importNovel: null })}
                onProjectRouteChange={(projectId) => updateRoute({
                  page: 'creation',
                  project: projectId || null,
                })}
                onHeaderContextChange={setHeaderContext}
              />
            </ErrorBoundary>
          ) : activeNav === 'image' ? (
            <ErrorBoundary scope="图像生成" fallbackTitle="图像生成加载失败">
              <ImageGenerationPage models={models} />
            </ErrorBoundary>
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
                  onClick={() => updateRoute({ page: 'settings', tab: 'models' })}
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
                  onClick={() => updateRoute({ page: 'settings', tab: 'prompts' })}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
                    <path d="M4 5h16M4 12h16M4 19h10" stroke="currentColor" strokeLinecap="round" />
                  </svg>
                  提示词管理
                </button>
              </div>
              {settingsTab === 'models' ? (
                <ErrorBoundary scope="模型配置" fallbackTitle="模型配置加载失败">
                  <ModelConfigPanel configs={models} refetch={fetchModels} />
                </ErrorBoundary>
              ) : (
                <ErrorBoundary scope="提示词管理" fallbackTitle="提示词管理加载失败">
                  <PromptManagerPanel />
                </ErrorBoundary>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
