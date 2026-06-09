// AI 小说创作 - Notion 文档式主壳
// 整体布局: 顶栏 (项目切换 + 流程进度 + 操作) + 三栏 (章节大纲 | 主工作区 | 设定/参考)
// 全屏高度 100vh, 不需要页面滚动
// 入口界面: ProjectListView (项目网格) — NotionWorkspace (项目详情)
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../../api/client.js';
import { useToast } from '../Toast/ToastProvider.jsx';
import { useCreationTask } from '../../state/CreationTaskContext.jsx';
import { ProjectForm } from './ProjectForm.jsx';
import { ProjectIntakeWizard } from './ProjectIntakeWizard.jsx';
import { ChapterGenerator } from './ChapterGenerator.jsx';
import { VariantCards } from './VariantCards.jsx';
import { VariantEditor } from './VariantEditor.jsx';
import { ProjectKGPreview } from './ProjectKGPreview.jsx';
import { KGGraphView } from './KGGraphView.jsx';
import './creation.css';

// 持久化最近一次打开的项目 ID, 让"刷新页面/重连任务"后能自动回到原项目,
// 配合 CreationTaskContext 形成完整的"任务不丢"体验.
const ACTIVE_PROJECT_KEY = 'ainovel.creation.activeProject.v1';
function readActiveProject() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(ACTIVE_PROJECT_KEY);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}
function writeActiveProject(id) {
  if (typeof window === 'undefined') return;
  try {
    if (id == null) window.localStorage.removeItem(ACTIVE_PROJECT_KEY);
    else window.localStorage.setItem(ACTIVE_PROJECT_KEY, String(id));
  } catch { /* noop */ }
}

// ============================================================
// 流程进度常量
// ============================================================
const FLOW_STEPS = [
  { key: 'intent',   label: '输入意图' },
  { key: 'generate', label: '生成候选' },
  { key: 'select',   label: '选择版本' },
  { key: 'edit',     label: '编辑正文' },
  { key: 'confirm',  label: '入图谱' },
];

function getCurrentStep(chapter, generating) {
  if (generating) return 'generate';
  if (!chapter) return 'intent';
  switch (chapter.status) {
    case 'generating': return 'generate';
    case 'generated':  return 'select';
    case 'selected':
    case 'edited':     return 'edit';
    case 'confirmed':  return 'confirm';
    default:           return 'intent';
  }
}

const SUB_STAGE_PROGRESS = {
  start: 0.05,
  planner_done: 0.30,
  writer_0_done: 0.45,
  writer_1_done: 0.60,
  writer_2_done: 0.75,
  critic_0_done: 0.85,
  critic_1_done: 0.92,
  critic_2_done: 0.97,
  done: 1.0,
};

function getGenerationProgressPercent(progress) {
  if (!progress || !progress.stage) return 0;
  if (progress.error) return 0;
  return SUB_STAGE_PROGRESS[progress.stage] ?? 0;
}

function formatDateTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch (e) {
    return '';
  }
}

// ============================================================
// 主组件
// ============================================================
export function CreationStudio({ models = [], topSearch = '' }) {
  const toast = useToast();
  const creationTask = useCreationTask();
  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  // 从 localStorage 恢复最近一次打开的项目 — 配合 CreationTaskContext, 刷
  // 新页面后能直接续上项目 + 后台任务进度.
  const [activeProjectId, setActiveProjectIdState] = useState(() => readActiveProject());
  const setActiveProjectId = useCallback((id) => {
    writeActiveProject(id);
    setActiveProjectIdState(id);
  }, []);
  const [projectDetail, setProjectDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [editingProject, setEditingProject] = useState(false);
  const [submittingProject, setSubmittingProject] = useState(false);

  const [activeChapterId, setActiveChapterId] = useState(null);
  const [chapterDetail, setChapterDetail] = useState(null);
  const [chapterLoading, setChapterLoading] = useState(false);

  // 章节生成任务委托给 CreationTaskContext, 以便刷新/切页后状态可恢复.
  // 这里只根据 context 状态派生本组件 UI 所需的 ``generating`` / ``genProgress``.
  // 当 context 中任务对应的 project 与当前 activeProjectId 一致时才显示进度,
  // 避免别的项目里残留任务把本项目的画布覆盖掉.
  const generating = !!(
    creationTask.running &&
    activeProjectId != null &&
    creationTask.projectId === activeProjectId
  );
  const genProgress =
    creationTask.projectId === activeProjectId ? creationTask.genProgress : null;

  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [kgRefreshKey, setKgRefreshKey] = useState(0);

  // 过滤项目列表 (按 topSearch)
  const filteredProjects = useMemo(() => {
    if (!topSearch.trim()) return projects;
    const q = topSearch.toLowerCase();
    return projects.filter((p) =>
      (p.title || '').toLowerCase().includes(q) ||
      (p.genre || '').toLowerCase().includes(q) ||
      (p.outline || '').toLowerCase().includes(q)
    );
  }, [projects, topSearch]);

  // ---- 项目列表 ----
  const loadProjects = useCallback(async () => {
    setProjectsLoading(true);
    try {
      const data = await api.creation.listProjects();
      setProjects(data.projects || []);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '加载项目失败');
    } finally {
      setProjectsLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadProjects(); }, [loadProjects]);

  // ---- 项目详情 ----
  const loadProjectDetail = useCallback(async (id) => {
    if (!id) {
      setProjectDetail(null);
      return;
    }
    setDetailLoading(true);
    try {
      const data = await api.creation.getProject(id);
      setProjectDetail(data);
      const lastCh = (data.chapters || [])[data.chapters.length - 1];
      if (lastCh) {
        setActiveChapterId(lastCh.id);
      } else {
        setActiveChapterId(null);
        setChapterDetail(null);
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '加载项目详情失败');
      setProjectDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadProjectDetail(activeProjectId);
  }, [activeProjectId, loadProjectDetail]);

  // ---- 章节详情 ----
  const loadChapterDetail = useCallback(async (chId) => {
    if (!chId) { setChapterDetail(null); return; }
    setChapterLoading(true);
    try {
      const data = await api.creation.getChapter(chId);
      setChapterDetail(data.chapter);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '加载章节失败');
      setChapterDetail(null);
    } finally {
      setChapterLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadChapterDetail(activeChapterId);
  }, [activeChapterId, loadChapterDetail]);

  // ---- 项目 CRUD ----
  const handleCreateProject = async (payload) => {
    setSubmittingProject(true);
    try {
      const res = await api.creation.createProject(payload);
      toast.success(`已创建: ${payload.title}`);
      setCreatingProject(false);
      await loadProjects();
      setActiveProjectId(res.id);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '创建失败');
    } finally {
      setSubmittingProject(false);
    }
  };

  const handleUpdateProject = async (payload) => {
    if (!activeProjectId) return;
    setSubmittingProject(true);
    try {
      await api.creation.updateProject(activeProjectId, payload);
      toast.success('已保存');
      setEditingProject(false);
      await loadProjectDetail(activeProjectId);
      await loadProjects();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '保存失败');
    } finally {
      setSubmittingProject(false);
    }
  };

  const handleDeleteProject = async () => {
    if (!activeProjectId) return;
    const p = projectDetail?.project;
    if (!p) return;
    if (!confirm(`确认删除项目「${p.title}」? 所有章节 / 变体 / 图谱将一并删除, 不可恢复.`)) return;
    try {
      await api.creation.deleteProject(activeProjectId);
      toast.success('已删除');
      setActiveProjectId(null);
      setProjectDetail(null);
      setActiveChapterId(null);
      setChapterDetail(null);
      await loadProjects();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '删除失败');
    }
  };

  const handleSeedKG = async () => {
    if (!activeProjectId) return;
    try {
      const r = await api.creation.seedKG(activeProjectId);
      toast.success(`已灌入 ${r.characters || 0} 个人物到知识图谱`);
      setKgRefreshKey((k) => k + 1);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '灌入失败');
    }
  };

  const handleClearKG = async () => {
    if (!activeProjectId) return;
    if (!confirm('确认清空本项目的知识图谱? 此操作不可恢复.')) return;
    try {
      await api.creation.clearKG(activeProjectId);
      toast.success('已清空');
      setKgRefreshKey((k) => k + 1);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '清空失败');
    }
  };

  // ---- 章节生成 (SSE) ----
  // 把 SSE 业务事件/状态/取消全权委托给 CreationTaskContext, 本函数只负责
  // 把 UI 侧的事件 (e.g. 自动同步章节 title) 转译给 context. 任务的"持久化 /
  // 跨连接取消 / 刷新后重连"由 context 层统一处理.
  const handleGenerate = useCallback(
    ({ user_intent, title, chapter_no }) => {
      if (!activeProjectId) return;
      creationTask.startGeneration({
        targetProjectId: activeProjectId,
        projectTitle: projectDetail?.project?.title,
        userIntent: user_intent,
        chapterNo: chapter_no,
        title,
        // 默认走 "single" 模式: 一次只产 1 个候选, Critic 评分不达标自动
        // 回到 Planner + Writer 改写, 最多重试 2 轮 (含首次共 3 次尝试),
        // 综合分 >= 7.0 视为通过. 旧 3 候选体验可通过 mode='candidates' 启用.
        mode: 'single',
        maxRevise: 2,
        scoreThreshold: 7.0,
        onProgress: (ev) => {
          // 同步 autoTitle 到当前 chapter detail, 让左侧大纲的标题立刻更新
          const data = ev.data || {};
          if (data.event === 'title_generated' && data.chapter_id) {
            setChapterDetail((cd) =>
              cd && cd.id === data.chapter_id ? { ...cd, title: data.title } : cd
            );
          }
          if (data.event === 'done' && data.chapter_id && data.title) {
            setChapterDetail((cd) =>
              cd && cd.id === data.chapter_id ? { ...cd, title: data.title } : cd
            );
          }
        },
        onComplete: async (ev) => {
          // 兼容 ``ev`` 自身携带 event / 或者 ev.data.event 这两种历史结构
          const data = ev?.data || ev || {};
          if (ev?.event === 'done' || data.event === 'done') {
            // single 模式: done 事件携带 final_score / accepted, 用作提示
            const score = typeof data.final_score === 'number' ? data.final_score : null;
            const accepted = data.accepted !== false;
            const attempts = data.attempts;
            if (accepted && score != null) {
              toast.success(`章节生成完成 (评分 ${score.toFixed(1)}, ${attempts} 轮)`);
            } else if (score != null) {
              toast.warning(`章节已生成但 Critic 未通过 (${score.toFixed(1)} < ${data.event === 'done' ? '' : ''}阈值)`);
            } else {
              toast.success('章节生成完成');
            }
            await loadProjectDetail(activeProjectId);
            // 让大纲里看到"刚生成的章节"被自动选中, 变体视图立刻出现
            const newChapterId = data.chapter_id;
            if (newChapterId) {
              setActiveChapterId(newChapterId);
              await loadChapterDetail(newChapterId);
            }
          } else if (ev?.event === 'error' || data.event === 'error') {
            const msg = data.message || '生成失败';
            toast.error(msg);
          }
        },
      });
    },
    [activeProjectId, creationTask, loadChapterDetail, loadProjectDetail, projectDetail, toast]
  );

  // ---- 章节操作 ----
  const handleSelectVariant = async (variantId) => {
    if (!activeChapterId) return;
    try {
      await api.creation.selectVariant(activeChapterId, variantId);
      toast.success('已选择此版本');
      await loadChapterDetail(activeChapterId);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '选择失败');
    }
  };

  const handleEditVariant = (variant) => {
    if (chapterDetail?.selected_variant_id !== variant.id) {
      handleSelectVariant(variant.id);
    }
  };

  const handleSaveContent = async (content) => {
    if (!activeChapterId) return;
    setSaving(true);
    try {
      await api.creation.updateContent(activeChapterId, content);
      await loadChapterDetail(activeChapterId);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '保存失败');
      throw e;
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmChapter = async () => {
    if (!activeChapterId) return;
    setConfirming(true);
    try {
      await api.creation.confirmChapter(activeChapterId);
      toast.success('已确认, 知识图谱已更新');
      await loadChapterDetail(activeChapterId);
      setKgRefreshKey((k) => k + 1);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '确认失败');
    } finally {
      setConfirming(false);
    }
  };

  // ---- 章节管理 (导出 / 删除 / 重新生成) ----
  const handleExportChapter = (chapter) => {
    if (!chapter) return;
    const url = api.creation.exportChapterUrl(chapter.id, 'txt');
    const a = document.createElement('a');
    a.href = url;
    a.style.display = 'none';
    a.download = '';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 0);
  };

  const handleDeleteChapter = async (chapter) => {
    if (!chapter) return;
    if (!confirm(
      `确认删除第 ${chapter.chapter_no} 章「${chapter.title || '(未命名)'}」?\n`
      + `所有变体将被一并删除, 不可恢复.`
    )) return;
    setDeleting(true);
    try {
      await api.creation.deleteChapter(chapter.id);
      toast.success('已删除');
      if (activeChapterId === chapter.id) {
        setActiveChapterId(null);
        setChapterDetail(null);
      }
      await loadProjectDetail(activeProjectId);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  // 重新生成: 复用 handleGenerate (后端会按 chapter_no 覆盖)
  const [regenOf, setRegenOf] = useState(null);
  const handleRegenerateChapter = (chapter) => {
    if (!chapter) return;
    setRegenOf(chapter);
    setActiveChapterId(chapter.id);
    setChapterDetail(null);
  };

  // ============================================================
  // 渲染
  // ============================================================
  if (creatingProject) {
    return (
      <div className="creation-studio">
        <div className="creation-main-section">
          <h2>新建创作项目</h2>
          <ProjectIntakeWizard
            models={models}
            onSubmit={handleCreateProject}
            onCancel={() => setCreatingProject(false)}
            submitting={submittingProject}
          />
        </div>
      </div>
    );
  }

  if (!activeProjectId || !projectDetail) {
    return (
      <ProjectListView
        projects={filteredProjects}
        loading={projectsLoading}
        onSelectProject={(id) => { setActiveProjectId(id); setRegenOf(null); }}
        onCreateNew={() => setCreatingProject(true)}
      />
    );
  }

  return (
    <NotionWorkspace
      activeProjectId={activeProjectId}
      onSelectProject={(id) => { setActiveProjectId(id); setRegenOf(null); }}
      onCreateNew={() => setCreatingProject(true)}
      onBackToProjects={() => {
        setActiveProjectId(null);
        setProjectDetail(null);
        setActiveChapterId(null);
        setChapterDetail(null);
        setRegenOf(null);
        setEditingProject(false);
      }}
      projectDetail={projectDetail}
      chapterDetail={chapterDetail}
      chapterLoading={chapterLoading}
      generating={generating}
      genProgress={genProgress}
      saving={saving}
      confirming={confirming}
      deleting={deleting}
      regenOf={regenOf}
      setRegenOf={setRegenOf}
      kgRefreshKey={kgRefreshKey}
      editingProject={editingProject}
      submittingProject={submittingProject}
      setEditingProject={setEditingProject}
      handleUpdateProject={handleUpdateProject}
      handleDeleteProject={handleDeleteProject}
      handleSeedKG={handleSeedKG}
      handleClearKG={handleClearKG}
      setActiveChapterId={setActiveChapterId}
      handleGenerate={handleGenerate}
      handleSelectVariant={handleSelectVariant}
      handleEditVariant={handleEditVariant}
      handleSaveContent={handleSaveContent}
      handleConfirmChapter={handleConfirmChapter}
      handleExportChapter={handleExportChapter}
      handleDeleteChapter={handleDeleteChapter}
      handleRegenerateChapter={handleRegenerateChapter}
    />
  );
}

// ============================================================
// 入口界面: 项目列表视图 (网格卡片)
// ============================================================
function ProjectListView({ projects = [], loading = false, onSelectProject, onCreateNew }) {
  const [topSearch, setTopSearch] = useState('');
  const filtered = useMemo(() => {
    if (!topSearch.trim()) return projects;
    const q = topSearch.toLowerCase();
    return projects.filter(
      (p) =>
        (p.title || '').toLowerCase().includes(q) ||
        (p.genre || '').toLowerCase().includes(q) ||
        (p.outline || '').toLowerCase().includes(q)
    );
  }, [projects, topSearch]);

  return (
    <div className="creation-studio creation-project-list-view">
      <header className="creation-topbar">
        <div className="creation-topbar-left">
          <span className="creation-topbar-title">📖 AI 小说创作 · 我的项目</span>
        </div>
        <div className="creation-topbar-center">
          <input
            type="text"
            className="form-input creation-topbar-search"
            placeholder="搜索项目名 / 类型 / 设定…"
            value={topSearch}
            onChange={(e) => setTopSearch(e.target.value)}
            aria-label="搜索项目"
          />
        </div>
        <div className="creation-topbar-right">
          <button
            type="button"
            className="btn btn-primary"
            onClick={onCreateNew}
          >
            + 新建项目
          </button>
        </div>
      </header>

      <div className="creation-project-list-body">
        {loading ? (
          <p className="muted">加载项目…</p>
        ) : projects.length === 0 ? (
          <div className="creation-project-list-empty">
            <h3>还没有项目</h3>
            <p className="muted">点击右上角「+ 新建项目」开始创作</p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={onCreateNew}
              style={{ marginTop: 16 }}
            >
              + 新建创作项目
            </button>
          </div>
        ) : (
          <>
            <div className="creation-project-list-header">
              <h2>我的项目 ({filtered.length})</h2>
              <span className="muted small">点击卡片进入项目</span>
            </div>
            <div className="creation-project-grid">
              {filtered.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="creation-project-card-large"
                  onClick={() => onSelectProject(p.id)}
                  title={`进入项目「${p.title}」`}
                >
                  <div className="creation-project-card-large-icon">📖</div>
                  <div className="creation-project-card-large-body">
                    <h3 className="creation-project-card-large-title">
                      {p.title || '未命名项目'}
                    </h3>
                    <div className="creation-project-card-large-meta muted small">
                      {p.genre || '—'} · 第 {p.current_chapter_no || 1} 章
                    </div>
                    {(p.worldview || p.outline) && (
                      <p className="creation-project-card-large-desc muted small">
                        {(p.outline || p.worldview).slice(0, 80)}
                        {(p.outline || p.worldview).length > 80 ? '…' : ''}
                      </p>
                    )}
                    {p.updated_at && (
                      <div className="creation-project-card-large-time muted small">
                        更新: {formatDateTime(p.updated_at)}
                      </div>
                    )}
                  </div>
                  <span className="creation-project-card-large-arrow" aria-hidden="true">→</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Notion 风格主工作区
// ============================================================
function NotionWorkspace(props) {
  const {
    onSelectProject, onCreateNew, onBackToProjects,
    projectDetail, chapterDetail, chapterLoading,
    generating, genProgress, saving, confirming, deleting, regenOf, setRegenOf,
    kgRefreshKey, editingProject, submittingProject, setEditingProject,
    handleUpdateProject, handleDeleteProject, handleSeedKG, handleClearKG,
    setActiveChapterId, handleGenerate, handleSelectVariant, handleEditVariant,
    handleSaveContent, handleConfirmChapter, handleExportChapter,
    handleDeleteChapter, handleRegenerateChapter,
  } = props;

  const project = projectDetail.project;
  const chapters = projectDetail.chapters || [];
  const kgStats = projectDetail.kg_stats || {};
  const nextChapterNo = project.current_chapter_no || 1;
  const hasConcepts = (project.initial_concepts || []).length > 0;

  const currentStep = useMemo(
    () => getCurrentStep(chapterDetail, generating),
    [chapterDetail, generating]
  );
  const progressPercent = useMemo(
    () => getGenerationProgressPercent(genProgress),
    [genProgress]
  );

  const [referenceOpen, setReferenceOpen] = useState(true);

  return (
    <div className="creation-studio">
      <div className="creation-workspace creation-workspace-notion">
        <header className="creation-topbar">
          <div className="creation-topbar-left">
            <button
              type="button"
              className="creation-topbar-back"
              onClick={onBackToProjects}
              title="返回项目列表"
            >
              ← 返回项目列表
            </button>
            <span className="creation-topbar-project-title">
              {project.title || '未命名项目'}
            </span>
          </div>

          <div className="creation-topbar-center">
            <FlowProgressCompact
              currentStep={currentStep}
              generating={generating}
            />
            {generating && (
              <div className="creation-topbar-mini-progress" title="生成进度">
                <div className="creation-topbar-mini-bar">
                  <div
                    className="creation-topbar-mini-bar-fill"
                    style={{ width: `${Math.round(progressPercent * 100)}%` }}
                  />
                </div>
                <span>{Math.round(progressPercent * 100)}%</span>
              </div>
            )}
          </div>

          <div className="creation-topbar-right">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={onCreateNew}
              title="新建一个创作项目"
            >
              + 新建项目
            </button>
            <div className="creation-topbar-divider" />
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setEditingProject(!editingProject)}
              title="编辑项目设定"
            >
              ⚙ 设定
            </button>
            {hasConcepts && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={handleSeedKG}
                title="把初始人物灌入知识图谱"
              >
                📊 灌入
              </button>
            )}
            {(kgStats.characters || 0) > 0 && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={handleClearKG}
                title="清空知识图谱"
              >
                🗑 清空
              </button>
            )}
            <div className="creation-topbar-divider" />
            <button
              type="button"
              className="creation-reference-toggle"
              onClick={() => setReferenceOpen((v) => !v)}
              title={referenceOpen ? '隐藏右侧参考面板' : '显示右侧参考面板'}
              aria-label={referenceOpen ? '隐藏右侧' : '显示右侧'}
            >
              {referenceOpen ? '»' : '«'}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm danger"
              onClick={handleDeleteProject}
              title="删除项目"
            >
              ×
            </button>
          </div>

          <div className="creation-topbar-progress" aria-hidden="true">
            <div
              className="creation-topbar-progress-bar"
              style={{ width: `${progressPercent * 100}%` }}
            />
          </div>
        </header>

        <div
          className={
            'creation-workspace-body creation-workspace-notion-body'
            + (referenceOpen ? '' : ' is-reference-collapsed')
          }
        >
          <ChapterOutlinePane
            chapters={chapters}
            activeChapterId={chapterDetail?.id}
            nextChapterNo={nextChapterNo}
            generating={generating}
            onSelectChapter={(ch) => { setActiveChapterId(ch.id); setRegenOf(null); }}
            onExportChapter={handleExportChapter}
            onRegenerateChapter={handleRegenerateChapter}
            onDeleteChapter={handleDeleteChapter}
            onGenerateNext={() => { setActiveChapterId(null); setRegenOf(null); }}
          />

          <CanvasPane
            project={project}
            chapterDetail={chapterDetail}
            chapterLoading={chapterLoading}
            generating={generating}
            genProgress={genProgress}
            saving={saving}
            confirming={confirming}
            regenOf={regenOf}
            setRegenOf={setRegenOf}
            handleGenerate={handleGenerate}
            handleSelectVariant={handleSelectVariant}
            handleEditVariant={handleEditVariant}
            handleSaveContent={handleSaveContent}
            handleConfirmChapter={handleConfirmChapter}
            handleExportChapter={handleExportChapter}
            handleDeleteChapter={handleDeleteChapter}
            handleRegenerateChapter={handleRegenerateChapter}
          />

          <ReferencePane
            open={referenceOpen}
            project={project}
            kgStats={kgStats}
            kgRefreshKey={kgRefreshKey}
            editingProject={editingProject}
            setEditingProject={setEditingProject}
            submittingProject={submittingProject}
            handleUpdateProject={handleUpdateProject}
            handleSeedKG={handleSeedKG}
            handleClearKG={handleClearKG}
            hasConcepts={hasConcepts}
            onToggle={() => setReferenceOpen((v) => !v)}
            threads={projectDetail.plot_threads || []}
            locations={projectDetail.locations || []}
            themesProgress={projectDetail.themes_progress || []}
            kgChars={projectDetail.kg_full?.characters || []}
            kgEvents={projectDetail.kg_full?.events || []}
            kgLocations={projectDetail.kg_full?.locations || []}
            kgCharRels={projectDetail.kg_full?.character_relations || []}
            kgCharEventRels={projectDetail.kg_full?.character_event_relations || []}
            kgEventRels={projectDetail.kg_full?.event_relations || []}
            activeChapter={chapterDetail}
          />
        </div>
      </div>
    </div>
  );
}

// ============================================================
// 顶栏: 紧凑版流程进度 (5 步 inline)
// ============================================================
function FlowProgressCompact({ currentStep, generating }) {
  const curIdx = FLOW_STEPS.findIndex((s) => s.key === currentStep);
  return (
    <ol
      className="creation-flow-progress creation-flow-progress-compact"
      aria-label="章节生成流程"
    >
      {FLOW_STEPS.map((s, i) => {
        const isDone = i < curIdx;
        const isActive = i === curIdx;
        const isCurrentGenerating = isActive && s.key === 'generate' && generating;
        return (
          <li
            key={s.key}
            className={
              'creation-flow-step'
              + (isDone ? ' is-done' : '')
              + (isActive ? ' is-active' : '')
              + (isCurrentGenerating ? ' is-running' : '')
            }
          >
            <span className="creation-flow-num">
              {isDone ? '✓' : (i + 1)}
            </span>
            <span className="creation-flow-label">{s.label}</span>
            {isCurrentGenerating && (
              <span className="creation-flow-pulse" aria-hidden="true">
                <span
                  style={{
                    display: 'inline-block',
                    width: 6,
                    height: 6,
                    borderRadius: 3,
                    background: 'var(--accent-color, #6366f1)',
                    animation: 'creation-flow-pulse 1.2s ease-in-out infinite',
                  }}
                />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ============================================================
// 左栏: 章节大纲 (主导航)
// ============================================================
function ChapterOutlinePane({
  chapters, activeChapterId, nextChapterNo, generating,
  onSelectChapter, onExportChapter, onRegenerateChapter, onDeleteChapter,
  onGenerateNext,
}) {
  return (
    <aside className="creation-toc-pane">
      <div className="creation-toc-pane-head">
        <h3>📑 章节大纲</h3>
        <span className="muted small">{chapters.length} 章</span>
      </div>
      <div className="creation-toc-pane-body">
        {chapters.length === 0 ? (
          <p className="muted small" style={{ padding: '8px 4px' }}>
            还没有章节, 点击下方按钮开始
          </p>
        ) : (
          chapters.map((ch) => (
            <ChapterTOCItem
              key={ch.id}
              chapter={ch}
              active={ch.id === activeChapterId}
              onSelect={() => onSelectChapter(ch)}
              onExport={() => onExportChapter(ch)}
              onRegenerate={() => onRegenerateChapter(ch)}
              onDelete={() => onDeleteChapter(ch)}
            />
          ))
        )}
      </div>
      <div className="creation-toc-pane-foot">
        <button
          type="button"
          className="btn btn-primary btn-block"
          onClick={onGenerateNext}
          disabled={generating}
        >
          + 生成第 {nextChapterNo} 章
        </button>
      </div>
    </aside>
  );
}

function ChapterTOCItem({ chapter, active, onSelect, onExport, onRegenerate, onDelete }) {
  const status = chapter.status;
  const statusBadge = (() => {
    switch (status) {
      case 'confirmed':  return { dot: '✓', cls: 'confirmed' };
      case 'selected':   return { dot: '●', cls: 'selected' };
      case 'edited':     return { dot: '●', cls: 'edited' };
      case 'generated':  return { dot: '○', cls: 'generated' };
      case 'generating': return { dot: '⋯', cls: 'generating' };
      default:           return { dot: '·', cls: 'unknown' };
    }
  })();

  return (
    <div className={`creation-toc-item ${active ? 'active' : ''}`}>
      <button
        type="button"
        className="creation-toc-item-main"
        onClick={onSelect}
        title={`第 ${chapter.chapter_no} 章 · ${chapter.title || '(未命名)'}`}
      >
        <span className={`creation-toc-dot status-${statusBadge.cls}`}>
          {statusBadge.dot}
        </span>
        <span className="creation-toc-num">第 {chapter.chapter_no} 章</span>
        <span className="creation-toc-title">
          {chapter.title || <span className="muted">(未命名)</span>}
        </span>
        {chapter.word_count > 0 && (
          <span className="creation-toc-wc muted small">
            {chapter.word_count}字
          </span>
        )}
      </button>
      <div className="creation-toc-actions">
        <button
          type="button"
          className="icon-btn"
          onClick={(e) => { e.stopPropagation(); onExport(); }}
          title="导出 TXT"
          aria-label="导出"
        >
          ⤓
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={(e) => { e.stopPropagation(); onRegenerate(); }}
          title="重新生成"
          aria-label="重新生成"
          disabled={chapter.status === 'generating'}
        >
          ↻
        </button>
        <button
          type="button"
          className="icon-btn danger"
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          title="删除"
          aria-label="删除"
        >
          ×
        </button>
      </div>
    </div>
  );
}

// ============================================================
// 中栏: 主工作区 (Canvas)
// ============================================================
function CanvasPane({
  project, chapterDetail, chapterLoading,
  generating, genProgress, saving, confirming,
  regenOf, setRegenOf,
  handleGenerate, handleSelectVariant, handleEditVariant,
  handleSaveContent, handleConfirmChapter,
  handleExportChapter, handleDeleteChapter, handleRegenerateChapter,
}) {
  const nextChapterNo = project.current_chapter_no || 1;
  const isRegen = !!regenOf;

  // 标题优先级: regen > 当前 chapter.title > 自动生成的标题(生成中) > 默认
  const autoTitle = genProgress?.autoTitle;

  let headTitle, headHint;
  if (isRegen) {
    headTitle = `↻ 重新生成第 ${regenOf.chapter_no} 章`;
    headHint = `原标题: ${regenOf.title || '(未命名)'} · 状态: ${regenOf.status}`;
  } else if (chapterDetail) {
    headTitle = `第 ${chapterDetail.chapter_no} 章 · ${chapterDetail.title || '(未命名)'}`;
    headHint = `状态: ${chapterDetail.status} · ${chapterDetail.word_count} 字`;
  } else if (autoTitle && generating) {
    headTitle = `第 ${nextChapterNo} 章 · ${autoTitle}`;
    headHint = 'AI 已自动生成标题, 正在撰写正文…';
  } else {
    headTitle = `生成第 ${nextChapterNo} 章`;
    headHint = '为下一章提供意图, AI 会自动生成 3 个候选版本';
  }

  return (
    <main className="creation-canvas-pane">
      <div className="creation-canvas-pane-inner">
        <header className="creation-canvas-head">
          <div>
            <h2>{headTitle}</h2>
            <div className="muted small">{headHint}</div>
          </div>
          {(chapterDetail || isRegen) && (() => {
            const targetChapter = chapterDetail || regenOf;
            return (
              <ChapterActions
                chapter={targetChapter}
                generating={generating}
                onExport={() => handleExportChapter(targetChapter)}
                onRegenerate={() => handleRegenerateChapter(targetChapter)}
                onDelete={() => handleDeleteChapter(targetChapter)}
              />
            );
          })()}
        </header>

        <div className="creation-canvas-body">
          {isRegen ? (
            <ChapterGenerator
              key={`regen-${regenOf.id}`}
              project={project}
              nextChapterNo={regenOf.chapter_no}
              generating={generating}
              progress={genProgress}
              regenMode
              initialTitle={regenOf.title}
              onGenerate={({ user_intent, title, chapter_no }) => {
                handleGenerate({ user_intent, title, chapter_no });
                setRegenOf(null);
              }}
              onCancelRegen={() => setRegenOf(null)}
            />
          ) : generating ? (
            <GenerationProgress progress={genProgress} />
          ) : !chapterDetail ? (
            <ChapterGenerator
              project={project}
              nextChapterNo={nextChapterNo}
              generating={generating}
              progress={genProgress}
              onGenerate={handleGenerate}
            />
          ) : chapterLoading ? (
            <p className="muted">加载章节中…</p>
          ) : chapterDetail.status === 'confirmed' ? (
            <ConfirmedView chapter={chapterDetail} onExport={() => handleExportChapter(chapterDetail)} />
          ) : chapterDetail.status === 'selected' || chapterDetail.status === 'edited' ? (
            <VariantEditor
              chapter={chapterDetail}
              initialContent={chapterDetail.final_content}
              onSave={handleSaveContent}
              onConfirm={handleConfirmChapter}
              saving={saving}
              confirming={confirming}
            />
          ) : (
            <VariantCards
              variants={chapterDetail.variants || []}
              selectedId={chapterDetail.selected_variant_id}
              onSelect={handleSelectVariant}
              onEdit={handleEditVariant}
              onConfirm={(v) => handleEditVariant(v)}
            />
          )}
        </div>
      </div>
    </main>
  );
}

// ============================================================
// 右栏: 设定 + KG (可折叠)
// ============================================================
function ReferencePane({
  open, project, kgStats, kgRefreshKey,
  editingProject, setEditingProject, submittingProject,
  handleUpdateProject, handleSeedKG, handleClearKG, hasConcepts, onToggle,
  threads = [], locations = [], themesProgress = [],
  kgChars = [], kgEvents = [], kgLocations = [],
  kgCharRels = [], kgCharEventRels = [], kgEventRels = [],
  activeChapter = null,
}) {
  if (!open) return null;

  const openThreads = threads.filter((t) => t.status === 'open' || t.status === 'hinting');
  const resolvedThreads = threads.filter((t) => t.status === 'resolved' || t.status === 'dropped');

  return (
    <aside className="creation-reference-pane">
      <div className="creation-reference-pane-head">
        <h3>📚 设定 / 参考</h3>
        <button
          type="button"
          className="creation-reference-toggle"
          onClick={onToggle}
          title="隐藏右侧参考面板"
          aria-label="隐藏右侧"
        >
          »
        </button>
      </div>
      <div className="creation-reference-pane-body">
        {/* 排版说明: 知识图谱相关放在最前, 让用户一进项目就看到 AI 已学到的
            实体 / 事件 / 关系. 项目设定挪到末尾并默认折叠, 避免长文本把
            真正关心的 KG 挤到滚动条看不见的位置. */}

        {/* ⑨ 主题进度 */}
        {themesProgress.length > 0 && (
          <section className="creation-reference-section">
            <h4>
              <span>主题进度</span>
              <span className="badge">{themesProgress.length} 个主题</span>
            </h4>
            <ul className="creation-theme-progress">
              {themesProgress.map((t, i) => {
                const p = Math.max(0, Math.min(1, Number(t.progress) || 0));
                return (
                  <li key={i} className="creation-theme-progress-item">
                    <div className="creation-theme-progress-label">
                      <span>{t.theme || '?'}</span>
                      <span className="creation-theme-progress-stage">
                        {Math.round(p * 100)}% · {t.stage || '铺垫'}
                      </span>
                    </div>
                    <div className="creation-theme-progress-bar">
                      <div
                        className="creation-theme-progress-fill"
                        style={{ width: `${p * 100}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* ⑤ 剧情线索 */}
        {threads.length > 0 && (
          <section className="creation-reference-section">
            <h4>
              <span>剧情线索</span>
              <span className="badge">{openThreads.length} 未结 / {threads.length} 总</span>
            </h4>
            <ul className="creation-thread-list">
              {openThreads.map((t, i) => (
                <li key={`o-${i}`} className="creation-thread-item">
                  <div className="creation-thread-item-head">
                    <span className="creation-thread-item-title" title={t.title}>
                      {t.title}
                    </span>
                    <span className={`creation-thread-status status-${t.status}`}>
                      {t.status}
                    </span>
                  </div>
                  <div className="creation-thread-item-head">
                    <span className="creation-thread-priority" title={`优先级 ${t.priority}/5`}>
                      {[1, 2, 3, 4, 5].map((n) => (
                        <span
                          key={n}
                          className={`creation-thread-priority-dot ${
                            n <= (t.priority || 0) ? 'is-filled' : ''
                          }`}
                        />
                      ))}
                    </span>
                    {t.thread_type && (
                      <span className="muted small">{t.thread_type}</span>
                    )}
                  </div>
                  {t.notes && <p className="creation-thread-notes">{t.notes}</p>}
                </li>
              ))}
              {resolvedThreads.length > 0 && (
                <li className="muted small" style={{ marginTop: 4 }}>
                  已回收/放弃 {resolvedThreads.length} 条 (折叠)
                </li>
              )}
            </ul>
          </section>
        )}

        {/* ④ 地点 */}
        {locations.length > 0 && (
          <section className="creation-reference-section">
            <h4>
              <span>地点</span>
              <span className="badge">{locations.length} 个</span>
            </h4>
            <ul className="creation-location-list">
              {locations.map((l) => (
                <li key={l.id} className="creation-location-item">
                  <span className="creation-location-item-name" title={l.name}>
                    {l.name}
                  </span>
                  {l.location_type && (
                    <span className="creation-location-type">{l.location_type}</span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* ⑩ KG Graph 可视化 */}
        <section className="creation-reference-section">
          <h4>
            <span>图谱视图</span>
            <span className="badge">SVG</span>
          </h4>
          <KGGraphView
            characters={kgChars}
            events={kgEvents}
            locations={kgLocations}
            characterRelations={kgCharRels}
            characterEventRelations={kgCharEventRels}
            eventRelations={kgEventRels}
          />
        </section>

        {/* ⑦ Compass 报告 (per-chapter) */}
        {activeChapter && activeChapter.compass_score != null && (
          <section className="creation-reference-section">
            <h4>
              <span>CompassAgent 偏离度</span>
              <span className="badge">
                {Number(activeChapter.compass_score).toFixed(1)} / 10
              </span>
            </h4>
            {activeChapter.compass_summary && (
              <p className="creation-compass-summary">{activeChapter.compass_summary}</p>
            )}
            {activeChapter.compass_warnings && activeChapter.compass_warnings.length > 0 && (
              <div>
                {activeChapter.compass_warnings.map((w, i) => (
                  <div
                    key={i}
                    className={`creation-compass-warning ${
                      w.severity === 'warn' ? 'dim' : ''
                    }`}
                  >
                    {w.text || w.dim}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        <section className="creation-reference-section">
          <h4>
            <span>知识图谱 (列表)</span>
            <span className="badge">
              {kgStats.characters || 0} 人物 / {kgStats.events || 0} 事件
            </span>
          </h4>
          <ProjectKGPreview projectId={project.id} refreshKey={kgRefreshKey} />
        </section>

        {/* 项目设定 — 默认折叠, 放在最末, 不挤 KG */}
        <section className="creation-reference-section creation-reference-section-collapsible">
          <details>
            <summary>
              <span className="creation-reference-section-summary-title">项目设定</span>
              <span className="badge">世界观 / 总纲 / 人物 / 文风</span>
            </summary>
            {editingProject ? (
              <ProjectForm
                initial={project}
                models={[]}
                isEdit
                submitting={submittingProject}
                onSubmit={handleUpdateProject}
                onCancel={() => setEditingProject(false)}
              />
            ) : (
              <div className="creation-project-readonly">
                <div className="muted small">
                  {project.genre || '—'} · 模型 {project.model_id || '默认'} · 第 {project.current_chapter_no || 1} 章
                </div>
                {project.worldview && (
                  <div className="creation-project-field">
                    <h5>世界观</h5>
                    <p>{project.worldview}</p>
                  </div>
                )}
                {project.outline && (
                  <div className="creation-project-field">
                    <h5>总纲</h5>
                    <p>{project.outline}</p>
                  </div>
                )}
                {hasConcepts && (
                  <div className="creation-project-field">
                    <h5>初始人物 ({project.initial_concepts.length})</h5>
                    <ul>
                      {project.initial_concepts.map((c, i) => (
                        <li key={i}>
                          <strong>{c.name}</strong>
                          {c.attributes && Object.keys(c.attributes).length > 0 && (
                            <span className="muted small"> · {JSON.stringify(c.attributes)}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {project.style_pref && Object.keys(project.style_pref).length > 0 && (
                  <div className="creation-project-field">
                    <h5>文风偏好</h5>
                    <ul>
                      {Object.entries(project.style_pref).map(([k, v]) => (
                        <li key={k}><strong>{k}</strong>: {String(v) || '—'}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="creation-project-card-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setEditingProject(true)}
                  >
                    ✎ 编辑设定
                  </button>
                </div>
              </div>
            )}
          </details>
        </section>
      </div>
    </aside>
  );
}

// ============================================================
// 操作按钮 (导出 / 重新生成 / 删除)
// ============================================================
function ChapterActions({ chapter, generating, onExport, onRegenerate, onDelete }) {
  const disabled = generating || !chapter;
  return (
    <div className="creation-chapter-actions">
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={onExport}
        disabled={disabled || !chapter.final_content}
        title="导出为 TXT"
      >
        ⤓ 导出 TXT
      </button>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={onRegenerate}
        disabled={disabled}
        title="用可选的新需求重新生成此章"
      >
        ↻ 重新生成
      </button>
      <button
        type="button"
        className="btn btn-ghost btn-sm danger"
        onClick={onDelete}
        disabled={disabled}
        title="删除此章"
      >
        × 删除
      </button>
    </div>
  );
}

// ============================================================
// 进度展示 + 已确认视图
// ============================================================
function GenerationProgress({ progress }) {
  if (!progress) {
    return <p className="muted small">准备生成…</p>;
  }
  const stage = progress.stage || 'start';
  const variants = progress.variants || {};
  const attemptScores = progress.attempt_scores || [];
  const isSingle = progress.mode === 'single' || variants[0] != null && variants[1] == null && variants[2] == null;
  const threshold = progress.score_threshold;
  return (
    <div className="creation-generation-progress">
      <h4>
        {isSingle ? '单候选生成' : '生成中'}: {stage}
        {progress.attempt ? ` · 第 ${progress.attempt} / ${progress.max_attempts || progress.max_revise + 1 || '?'} 轮` : ''}
      </h4>
      {isSingle && typeof threshold === 'number' && (
        <div className="muted small">
          Critic 通过阈值: ≥ {threshold.toFixed(1)}/10
          {attemptScores.length > 0 && (
            <> · 历次评分: {attemptScores
              .map((a) => `${a.attempt}:${a.score.toFixed(1)}`)
              .join(' / ')}</>
          )}
        </div>
      )}
      {progress.directions && progress.directions.length > 0 && (
        <div className="muted small">
          Planner 已生成 {progress.directions.length} 个分叉方向
          {isSingle && ' (本模式仅取方向 0 撰写)'}
        </div>
      )}
      {progress.bridge_score != null && (
        <div className="muted small">
          🔗 接缝质量 {progress.bridge_score.toFixed(1)}/10
          {progress.bridge_conflicts && progress.bridge_conflicts.length > 0 &&
            ` · ${progress.bridge_conflicts.length} 个承接冲突`}
        </div>
      )}
      {stage === 'revision_start' && (
        <p className="creation-progress-revision">
          🔁 第 {progress.attempt} 轮重做中 (上轮评分 {progress.previous_score?.toFixed(1)}/10 未达阈值)
        </p>
      )}
      {stage === 'critic_rejected' && progress.last_rejected && (
        <p className="creation-progress-rejection">
          ✗ 第 {progress.last_rejected.attempt} 轮 Critic 未通过
          ({progress.last_rejected.score?.toFixed(1)}/10
          {' < '}{progress.last_rejected.threshold?.toFixed(1)})
        </p>
      )}
      {Object.keys(variants).length > 0 && (
        <ul className="creation-progress-variants">
          {Object.entries(variants).map(([idx, v]) => {
            const i = Number(idx);
            return (
              <li key={i} className={`creation-progress-variant ${v.state || 'pending'}`}>
                <span>
                  {isSingle ? '正文' : `版本 ${i + 1}`}
                  {typeof v.word_count === 'number' ? ` (${v.word_count} 字)` : ''}
                </span>
                <span>
                  {v.state === 'done'
                    ? `✓ 通过 · 评分 ${v.score?.toFixed(1) ?? '?'}/10`
                    : v.state === 'rejected'
                      ? `✗ 未通过 · 评分 ${v.score?.toFixed(1) ?? '?'}/10`
                      : v.state === 'critiquing'
                        ? `Critic 审核中…`
                        : 'Planner / Writer 撰写中…'}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {progress.error && (
        <p className="creation-error small">{progress.error}</p>
      )}
    </div>
  );
}

function ConfirmedView({ chapter, onExport }) {
  return (
    <div className="creation-confirmed">
      <p className="muted small">✅ 本章已确认, 内容已固化入项目级知识图谱.</p>
      <details className="creation-final-content" open>
        <summary>查看最终正文 ({chapter.word_count} 字)</summary>
        <pre>{chapter.final_content}</pre>
      </details>
      <div className="creation-actions-row">
        <button type="button" className="btn btn-ghost" onClick={onExport}>
          ⤓ 导出 TXT
        </button>
      </div>
    </div>
  );
}
