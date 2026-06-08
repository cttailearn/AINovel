// AI 小说创作 - 主壳
// 左侧: 项目列表 + 新建按钮
// 右侧: 项目详情 (设定 / 章节列表 / 章节生成 / 三选一 / 编辑 / KG 预览)
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../../api/client.js';
import { useToast } from '../Toast/ToastProvider.jsx';
import { ProjectForm } from './ProjectForm.jsx';
import { ChapterList } from './ChapterList.jsx';
import { ChapterGenerator } from './ChapterGenerator.jsx';
import { VariantCards } from './VariantCards.jsx';
import { VariantEditor } from './VariantEditor.jsx';
import { ProjectKGPreview } from './ProjectKGPreview.jsx';
import './creation.css';

export function CreationStudio({ models = [], topSearch = '' }) {
  const toast = useToast();
  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [projectDetail, setProjectDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [editingProject, setEditingProject] = useState(false);
  const [submittingProject, setSubmittingProject] = useState(false);

  const [activeChapterId, setActiveChapterId] = useState(null);
  const [chapterDetail, setChapterDetail] = useState(null);
  const [chapterLoading, setChapterLoading] = useState(false);

  const [generating, setGenerating] = useState(false);
  const [genProgress, setGenProgress] = useState(null); // { stage, variants, error }
  const genAbortRef = useRef(null);

  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);

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
      // 默认选中最后一章 (最近的进度)
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
  const handleGenerate = async ({ user_intent, title, chapter_no }) => {
    if (!activeProjectId) return;
    setGenerating(true);
    setGenProgress({ stage: 'start', variants: {} });
    try {
      await api.creation.generate(
        activeProjectId,
        { user_intent, title, chapter_no },
        {
          onEvent: (ev) => {
            const data = ev.data || {};
            setGenProgress((prev) => {
              const next = { ...(prev || { stage: 'start', variants: {} }) };
              if (data.event === 'start') {
                next.stage = 'start';
                next.chapter_id = data.chapter_id;
                next.variants = {};
              } else if (data.event === 'planner_done') {
                next.stage = 'planner_done';
                next.directions = data.directions || [];
                next.variant_ids = data.variant_ids || [];
              } else if (data.event?.startsWith('writer_')) {
                const idx = Number(data.event.split('_')[1]);
                next.variants = {
                  ...(next.variants || {}),
                  [idx]: { state: 'critiquing', preview: data.preview, word_count: data.word_count },
                };
                next.stage = data.event;
              } else if (data.event?.startsWith('critic_')) {
                const idx = Number(data.event.split('_')[1]);
                next.variants = {
                  ...(next.variants || {}),
                  [idx]: {
                    ...(next.variants?.[idx] || {}),
                    state: 'done',
                    score: data.score,
                    variant_id: data.variant_id,
                  },
                };
                next.stage = data.event;
              } else if (data.event === 'done') {
                next.stage = 'done';
                next.chapter_id = data.chapter_id;
              } else if (data.event === 'error') {
                next.stage = 'error';
                next.error = data.message || '生成失败';
              }
              return next;
            });
          },
        }
      );
      toast.success('章节生成完成');
      // 重新加载详情, 让用户看到三选一卡片
      await loadProjectDetail(activeProjectId);
      setGenProgress(null);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '生成失败');
      setGenProgress((p) => ({ ...(p || {}), stage: 'error', error: e.message }));
    } finally {
      setGenerating(false);
    }
  };

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
    // 直接选中 + 进入编辑器
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

  // ============================================================
  // 渲染
  // ============================================================
  return (
    <div className="creation-studio">
      {/* 左侧: 项目列表 */}
      <aside className="creation-sidebar">
        <div className="creation-sidebar-head">
          <h3>创作项目</h3>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setCreatingProject(true)}
          >
            + 新建
          </button>
        </div>
        {projectsLoading ? (
          <p className="muted small">加载项目...</p>
        ) : filteredProjects.length === 0 ? (
          <p className="muted small">
            {projects.length === 0 ? '还没有项目, 点击「+ 新建」开始.' : '无匹配项目.'}
          </p>
        ) : (
          <ul className="creation-project-list">
            {filteredProjects.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className={`creation-project-item ${activeProjectId === p.id ? 'active' : ''}`}
                  onClick={() => setActiveProjectId(p.id)}
                >
                  <div className="creation-project-item-title">{p.title}</div>
                  <div className="creation-project-item-meta muted small">
                    {p.genre || '—'} · 第 {p.current_chapter_no} 章
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* 右侧: 主区 */}
      <main className="creation-main">
        {creatingProject ? (
          <div className="creation-main-section">
            <h2>新建创作项目</h2>
            <ProjectForm
              models={models}
              onSubmit={handleCreateProject}
              onCancel={() => setCreatingProject(false)}
              submitting={submittingProject}
            />
          </div>
        ) : !activeProjectId ? (
          <div className="creation-main-empty muted">
            <p>👈 在左侧选择项目, 或点击「+ 新建」开始创作.</p>
          </div>
        ) : detailLoading || !projectDetail ? (
          <div className="creation-main-empty muted">
            <p>加载项目详情...</p>
          </div>
        ) : (
          <ProjectDetailView
            projectDetail={projectDetail}
            editingProject={editingProject}
            setEditingProject={setEditingProject}
            submittingProject={submittingProject}
            handleUpdateProject={handleUpdateProject}
            handleDeleteProject={handleDeleteProject}
            handleSeedKG={handleSeedKG}
            handleClearKG={handleClearKG}
            chapterDetail={chapterDetail}
            chapterLoading={chapterLoading}
            setActiveChapterId={setActiveChapterId}
            handleGenerate={handleGenerate}
            generating={generating}
            genProgress={genProgress}
            handleSelectVariant={handleSelectVariant}
            handleEditVariant={handleEditVariant}
            handleSaveContent={handleSaveContent}
            handleConfirmChapter={handleConfirmChapter}
            saving={saving}
            confirming={confirming}
            kgRefreshKey={kgRefreshKey}
          />
        )}
      </main>
    </div>
  );
}

function ProjectDetailView({
  projectDetail,
  editingProject,
  setEditingProject,
  submittingProject,
  handleUpdateProject,
  handleDeleteProject,
  handleSeedKG,
  handleClearKG,
  chapterDetail,
  chapterLoading,
  setActiveChapterId,
  handleGenerate,
  generating,
  genProgress,
  handleSelectVariant,
  handleEditVariant,
  handleSaveContent,
  handleConfirmChapter,
  saving,
  confirming,
  kgRefreshKey,
}) {
  const project = projectDetail.project;
  const chapters = projectDetail.chapters || [];
  const kgStats = projectDetail.kg_stats || {};
  const nextChapterNo = project.current_chapter_no || 1;
  const hasConcepts = (project.initial_concepts || []).length > 0;

  return (
    <>
      {/* 项目设定 (可折叠) */}
      <section className="creation-main-section">
        <header className="creation-section-head">
          <h2>{project.title}</h2>
          <div className="creation-section-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setEditingProject(!editingProject)}
            >
              {editingProject ? '收起' : '编辑设定'}
            </button>
            {hasConcepts && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={handleSeedKG}>
                灌入种子图谱
              </button>
            )}
            {(kgStats.characters || 0) > 0 && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={handleClearKG}>
                清空图谱
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost btn-sm danger"
              onClick={handleDeleteProject}
            >
              删除项目
            </button>
          </div>
        </header>
        <div className="creation-project-meta muted small">
          {project.genre || '—'} · 模型 ID: {project.model_id || '默认'} · 当前进度: 第 {nextChapterNo} 章
        </div>
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
          </div>
        )}
      </section>

      {/* 章节生成器 + 章节列表 */}
      <section className="creation-main-section">
        <header className="creation-section-head">
          <h3>章节生成</h3>
        </header>
        <ChapterGenerator
          project={project}
          nextChapterNo={nextChapterNo}
          generating={generating}
          progress={genProgress}
          onGenerate={handleGenerate}
          onCancel={() => {
            // 真取消需要后端支持, 此处仅清空 UI
            setGenProgress(null);
          }}
        />
      </section>

      <section className="creation-main-section">
        <header className="creation-section-head">
          <h3>章节列表 ({chapters.length})</h3>
        </header>
        <ChapterList
          chapters={chapters}
          selectedChapterId={chapterDetail?.id}
          onSelect={setActiveChapterId}
          loading={chapterLoading && !chapterDetail}
          generating={generating}
        />
      </section>

      {/* 当前章节详情: 三选一 或 编辑器 */}
      {chapterDetail && (
        <section className="creation-main-section">
          <header className="creation-section-head">
            <h3>
              第 {chapterDetail.chapter_no} 章 · {chapterDetail.title || '(未命名)'}
            </h3>
            <span className="muted small">
              状态: {chapterDetail.status} · {chapterDetail.word_count} 字
            </span>
          </header>

          {chapterDetail.status === 'confirmed' ? (
            <>
              <p className="muted small">本章已确认, 内容已固化入项目级知识图谱.</p>
              <details className="creation-final-content">
                <summary>查看最终正文</summary>
                <pre>{chapterDetail.final_content}</pre>
              </details>
            </>
          ) : chapterDetail.status === 'generating' ? (
            <p className="muted small">生成中, 请稍候...</p>
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
        </section>
      )}

      {/* 知识图谱预览 */}
      <section className="creation-main-section">
        <header className="creation-section-head">
          <h3>项目级知识图谱</h3>
        </header>
        <ProjectKGPreview projectId={project.id} refreshKey={kgRefreshKey} />
      </section>
    </>
  );
}
