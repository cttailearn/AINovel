import { useEffect, useReducer, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { ConfirmDialog } from './Modal/ConfirmDialog.jsx';
import { useToast } from './Toast/ToastProvider.jsx';
import { PRESET_RULES, tryCompileRegex } from '../utils/regex.js';
import NovelReader from './NovelReader.jsx';

const DEFAULT_RULE = PRESET_RULES[0].value;
const STEPS = [
  { key: 'upload', label: '上传小说' },
  { key: 'parse', label: '解析目录' },
  { key: 'toc', label: '浏览章节' },
  { key: 'read', label: '开始阅读' },
];

function StepBar({ current }) {
  const activeIndex = Math.max(0, STEPS.findIndex((s) => s.key === current));
  return (
    <ol className="step-bar">
      {STEPS.map((step, idx) => {
        const state = idx < activeIndex ? 'done' : idx === activeIndex ? 'active' : 'todo';
        return (
          <li key={step.key} className={`step-item step-${state}`}>
            <span className="step-index">{idx + 1}</span>
            <span className="step-label">{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function StatusPill({ status }) {
  if (status === 'parsed') {
    return <span className="status-pill status-parsed">已解析</span>;
  }
  if (status === 'pending') {
    return <span className="status-pill status-pending">待解析</span>;
  }
  return <span className="status-pill">{status}</span>;
}

function formatTimestamp(value) {
  if (!value) return '—';
  try {
    const text = String(value).replace(' ', 'T');
    const d = new Date(text);
    if (Number.isNaN(d.getTime())) return value;
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch {
    return value;
  }
}

function NovelCard({ novel, onOpen, onStartReading, onDelete }) {
  return (
    <article
      className={`project-card ${novel.chapter_count > 0 ? 'has-chapters' : ''}`}
      onClick={() => onOpen(novel.id)}
    >
      <header className="project-card-head">
        <h3 className="project-card-title">{novel.title}</h3>
        <StatusPill status={novel.status} />
      </header>
      <p className="project-card-author">
        {novel.author || '未知作者'}
        {novel.filename && (
          <span className="project-card-filename"> · {novel.filename}</span>
        )}
      </p>
      <p className="project-card-desc">
        {novel.summary || '尚未生成内容预览，解析章节后会自动填充。'}
      </p>
      <footer className="project-card-foot">
        <span className="project-card-meta">
          {formatTimestamp(novel.created_at)}
          {novel.chapter_count > 0 && (
            <span className="project-card-chapters"> · {novel.chapter_count} 章</span>
          )}
        </span>
        <div className="project-card-actions" onClick={(e) => e.stopPropagation()}>
          {novel.chapter_count > 0 && (
            <button
              type="button"
              className="card-icon-btn"
              title="立即阅读"
              onClick={() => onStartReading(novel.id)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" stroke="currentColor" strokeWidth="2" />
                <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" stroke="currentColor" strokeWidth="2" />
              </svg>
            </button>
          )}
          <button
            type="button"
            className="card-icon-btn"
            title="编辑"
            onClick={() => onOpen(novel.id)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="2" />
              <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
          <button
            type="button"
            className="card-icon-btn danger"
            title="删除"
            onClick={() => onDelete?.(novel.id)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
        </div>
      </footer>
    </article>
  );
}

function UploadModal({ open, onClose, onUpload, uploading, progress }) {
  const inputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  const [picked, setPicked] = useState(null);

  useEffect(() => {
    if (!open) {
      setPicked(null);
      setDragOver(false);
    }
  }, [open]);

  if (!open) return null;

  const handleSelect = (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.txt')) {
      onUpload(new ApiError('仅支持 TXT 文件', 400, null), null);
      return;
    }
    setPicked(file);
  };

  const handleConfirm = () => {
    if (!picked) {
      inputRef.current?.click();
      return;
    }
    onUpload(null, picked);
  };

  return (
    <div className="upload-modal-backdrop" onClick={onClose}>
      <div className="upload-modal" onClick={(e) => e.stopPropagation()}>
        <header className="upload-modal-head">
          <h3>新建小说项目</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
        </header>
        <div
          className={`upload-dropzone ${dragOver ? 'is-over' : ''} ${picked ? 'has-file' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleSelect(e.dataTransfer.files?.[0]);
          }}
          onClick={() => inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".txt"
            style={{ display: 'none' }}
            onChange={(e) => {
              handleSelect(e.target.files?.[0]);
              e.target.value = '';
            }}
          />
          {picked ? (
            <>
              <div className="drop-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="2" />
                  <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </div>
              <strong>{picked.name}</strong>
              <span>{(picked.size / 1024).toFixed(1)} KB · 点击重新选择</span>
            </>
          ) : (
            <>
              <div className="drop-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" stroke="currentColor" strokeWidth="2" />
                  <path d="M17 8l-5-5-5 5M12 3v12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </div>
              <strong>点击或拖拽 TXT 文件到此处</strong>
              <span>支持 UTF-8 编码的纯文本，上传后可解析章节</span>
            </>
          )}
        </div>
        {uploading && progress && (
          <div className="upload-progress" role="progressbar" aria-valuenow={Math.round(progress.ratio * 100)}>
            <div className="upload-progress-bar" style={{ width: `${progress.ratio * 100}%` }} />
            <span className="upload-progress-text">上传中 {Math.round((progress?.ratio || 0) * 100)}%</span>
          </div>
        )}
        <footer className="upload-modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={uploading}>
            取消
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleConfirm}
            disabled={uploading}
          >
            {uploading ? '上传中...' : picked ? '开始上传' : '选择文件'}
          </button>
        </footer>
      </div>
    </div>
  );
}

const initialDetailState = {
  novel: null,
  loading: false,
  error: null,
  parseRule: DEFAULT_RULE,
  parsing: false,
  parseResult: null,
  preview: null,
  previewing: false,
  parsingFixed: false,
  editing: false,
  editTitle: '',
  editAuthor: '',
};

function detailReducer(state, action) {
  switch (action.type) {
    case 'LOAD_START':
      return { ...state, loading: true, error: null };
    case 'LOAD_OK':
      return {
        ...state,
        loading: false,
        novel: action.novel,
        parseRule: action.novel.parse_rule || DEFAULT_RULE,
        editTitle: action.novel.title,
        editAuthor: action.novel.author,
        parseResult: null,
        preview: null,
      };
    case 'LOAD_ERR':
      return { ...state, loading: false, error: action.error };
    case 'SET_RULE':
      return { ...state, parseRule: action.rule, parseResult: null, preview: null };
    case 'PARSE_START':
      return { ...state, parsing: true, parseResult: null, preview: null };
    case 'PARSE_OK':
      return { ...state, parsing: false, parseResult: action.result };
    case 'PARSE_ERR':
      return { ...state, parsing: false, parseResult: { success: false, message: action.error } };
    case 'PARSE_FIXED_START':
      return { ...state, parsingFixed: true, parseResult: null };
    case 'PARSE_FIXED_OK':
      return { ...state, parsingFixed: false, parseResult: action.result };
    case 'PARSE_FIXED_ERR':
      return { ...state, parsingFixed: false, parseResult: { success: false, message: action.error } };
    case 'PREVIEW_START':
      return { ...state, previewing: true, preview: null };
    case 'PREVIEW_OK':
      return { ...state, previewing: false, preview: action.preview };
    case 'PREVIEW_ERR':
      return { ...state, previewing: false, preview: { error: action.error } };
    case 'EDIT_START':
      return { ...state, editing: true, editTitle: action.title, editAuthor: action.author };
    case 'EDIT_FIELD':
      return { ...state, ...action.patch };
    case 'EDIT_END':
      return { ...state, editing: false };
    default:
      return state;
  }
}

function NovelWorkbench({ novelId, models, onBack, onStartReading, onChanged }) {
  const toast = useToast();
  const [state, dispatch] = useReducer(detailReducer, initialDetailState);
  const [chunkSize, setChunkSize] = useState(5000);
  const [activePane, setActivePane] = useState('toc');
  const abortRef = useRef(null);

  useEffect(() => {
    abortRef.current?.abort?.();
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: 'LOAD_START' });
    (async () => {
      try {
        const data = await api.novels.detail(novelId, { signal: controller.signal });
        dispatch({ type: 'LOAD_OK', novel: data });
      } catch (err) {
        if (err && err.name === 'AbortError') return;
        dispatch({ type: 'LOAD_ERR', error: err instanceof ApiError ? err.message : '加载失败' });
      }
    })();
    return () => controller.abort();
  }, [novelId]);

  const reload = async () => {
    try {
      const data = await api.novels.detail(novelId);
      dispatch({ type: 'LOAD_OK', novel: data });
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '刷新失败');
    }
  };

  const handlePreview = async () => {
    if (!state.parseRule.trim()) {
      toast.error('请输入解析规则');
      return;
    }
    const compile = tryCompileRegex(state.parseRule);
    if (!compile.ok) {
      toast.error(`无效正则: ${compile.error}`);
      return;
    }
    dispatch({ type: 'PREVIEW_START' });
    try {
      const preview = await api.novels.parsePreview(novelId, state.parseRule);
      dispatch({ type: 'PREVIEW_OK', preview });
      if (preview.chapters_found === 0) {
        toast.info('未匹配到任何章节');
      } else {
        toast.success(`预计将匹配 ${preview.chapters_found} 个章节`);
      }
    } catch (err) {
      dispatch({ type: 'PREVIEW_ERR', error: err instanceof ApiError ? err.message : '预览失败' });
      toast.error(err instanceof ApiError ? err.message : '预览失败');
    }
  };

  const handleParse = async () => {
    if (!state.parseRule.trim()) {
      toast.error('请输入解析规则');
      return;
    }
    const compile = tryCompileRegex(state.parseRule);
    if (!compile.ok) {
      toast.error(`无效正则: ${compile.error}`);
      return;
    }
    dispatch({ type: 'PARSE_START' });
    try {
      const result = await api.novels.parse(novelId, state.parseRule);
      dispatch({ type: 'PARSE_OK', result });
      if (result.success) {
        toast.success(result.message);
        setActivePane('toc');
        await reload();
      } else {
        toast.error(result.message || '解析失败');
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : '解析失败';
      dispatch({ type: 'PARSE_ERR', error: message });
      toast.error(message);
    }
  };

  const handleParseFixed = async () => {
    dispatch({ type: 'PARSE_FIXED_START' });
    try {
      const result = await api.novels.parseFixed(novelId, chunkSize);
      dispatch({ type: 'PARSE_FIXED_OK', result });
      toast.success(result.message || '固定字数解析完成');
      setActivePane('toc');
      await reload();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : '固定字数解析失败';
      dispatch({ type: 'PARSE_FIXED_ERR', error: message });
      toast.error(message);
    }
  };

  const handleSaveEdit = async () => {
    try {
      await api.novels.update(novelId, {
        title: state.editTitle,
        author: state.editAuthor,
      });
      toast.success('已更新');
      dispatch({ type: 'EDIT_END' });
      await reload();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '更新失败');
    }
  };

  if (state.loading) {
    return (
      <div className="workbench-panel loading">
        <div className="loading-spinner large"></div>
        <p>加载中...</p>
      </div>
    );
  }
  if (state.error || !state.novel) {
    return (
      <div className="workbench-panel error">
        <p>{state.error || '小说不存在'}</p>
        <button type="button" className="btn btn-primary" onClick={onBack}>
          返回工作台
        </button>
      </div>
    );
  }

  const chapters = state.novel.chapters || [];
  const hasChapters = chapters.length > 0;

  return (
    <div className="workbench-panel novel-workbench">
      <div className="panel-header">
        <button className="back-btn" type="button" onClick={onBack} title="返回">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        {state.editing ? (
          <div className="edit-form">
            <input
              type="text"
              value={state.editTitle}
              onChange={(e) =>
                dispatch({ type: 'EDIT_FIELD', patch: { editTitle: e.target.value } })
              }
              placeholder="小说标题"
            />
            <input
              type="text"
              value={state.editAuthor}
              onChange={(e) =>
                dispatch({ type: 'EDIT_FIELD', patch: { editAuthor: e.target.value } })
              }
              placeholder="作者"
            />
            <button className="save-edit-btn" type="button" onClick={handleSaveEdit}>
              保存
            </button>
            <button
              className="cancel-edit-btn"
              type="button"
              onClick={() => dispatch({ type: 'EDIT_END' })}
            >
              取消
            </button>
          </div>
        ) : (
          <div className="detail-title">
            <h2>{state.novel.title}</h2>
            <p>作者：{state.novel.author}</p>
          </div>
        )}
        <button
          className="edit-btn"
          type="button"
          onClick={() =>
            dispatch({
              type: 'EDIT_START',
              title: state.novel.title,
              author: state.novel.author,
            })
          }
          title="编辑"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="2" />
            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
      </div>

      <StepBar current={hasChapters ? 'toc' : 'parse'} />

      <div className="pane-tabs">
        <button
          type="button"
          className={`pane-tab ${activePane === 'parse' ? 'active' : ''}`}
          onClick={() => setActivePane('parse')}
        >
          解析目录
        </button>
        <button
          type="button"
          className={`pane-tab ${activePane === 'toc' ? 'active' : ''}`}
          onClick={() => setActivePane('toc')}
          disabled={!hasChapters}
        >
          章节列表 {hasChapters && <span className="pane-tag">{chapters.length}</span>}
        </button>
        <div className="pane-spacer" />
        {hasChapters && (
          <button
            type="button"
            className="start-reading-btn"
            onClick={() => onStartReading(novelId)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" stroke="currentColor" strokeWidth="2" />
              <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" stroke="currentColor" strokeWidth="2" />
            </svg>
            开始阅读
          </button>
        )}
      </div>

      {activePane === 'parse' && (
        <div className="parse-section">
          <div className="preset-rules">
            <span className="preset-label">预设规则：</span>
            {PRESET_RULES.map((rule) => (
              <button
                key={rule.value}
                type="button"
                className={`preset-btn ${state.parseRule === rule.value ? 'active' : ''}`}
                onClick={() => dispatch({ type: 'SET_RULE', rule: rule.value })}
                title={rule.value}
              >
                {rule.label}
              </button>
            ))}
          </div>

          <div className="rule-input-group">
            <input
              type="text"
              value={state.parseRule}
              onChange={(e) => dispatch({ type: 'SET_RULE', rule: e.target.value })}
              placeholder="输入正则表达式"
            />
            <button
              className="parse-btn ghost"
              type="button"
              onClick={handlePreview}
              disabled={state.previewing}
            >
              {state.previewing ? <span className="loading-spinner small"></span> : '预览'}
            </button>
            <button
              className="parse-btn"
              type="button"
              onClick={handleParse}
              disabled={state.parsing}
            >
              {state.parsing ? <span className="loading-spinner small"></span> : '解析'}
            </button>
          </div>

          <div className="rule-input-group">
            <label className="inline-label">固定字数：</label>
            <select value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))}>
              <option value={3000}>3000字</option>
              <option value={5000}>5000字</option>
              <option value={8000}>8000字</option>
              <option value={10000}>10000字</option>
            </select>
            <button
              className="parse-btn purple"
              type="button"
              onClick={handleParseFixed}
              disabled={state.parsingFixed}
            >
              {state.parsingFixed ? <span className="loading-spinner small"></span> : '按字数切分'}
            </button>
          </div>

          {state.preview && !state.preview.error && (
            <div className="parse-preview">
              <span>预计匹配 {state.preview.chapters_found} 个章节</span>
              {state.preview.preview?.length > 0 && (
                <ul className="preview-list">
                  {state.preview.preview.slice(0, 5).map((c) => (
                    <li key={c.chapter_number}>
                      #{c.chapter_number} {c.title}
                    </li>
                  ))}
                  {state.preview.preview.length > 5 && (
                    <li>... 等共 {state.preview.preview.length} 个</li>
                  )}
                </ul>
              )}
            </div>
          )}

          {state.parseResult && (
            <div className={`parse-result ${state.parseResult.success ? 'success' : 'error'}`}>
              <span>{state.parseResult.message}</span>
            </div>
          )}
        </div>
      )}

      {activePane === 'toc' && (
        <div className="chapters-section">
          {hasChapters ? (
            <div className="chapters-grid">
              {chapters.map((chapter) => (
                <button
                  key={chapter.id}
                  type="button"
                  className="chapter-item"
                  onClick={() => onStartReading(novelId, chapter.id)}
                  title="阅读本章"
                >
                  <span className="chapter-number">{chapter.chapter_number}</span>
                  <span className="chapter-title">{chapter.title}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="no-chapters">
              <p>暂无章节，请先在「解析目录」中设置规则并解析</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function Workbench({ models }) {
  const toast = useToast();
  const [view, setView] = useState('list');
  const [selectedId, setSelectedId] = useState(null);
  const [readingId, setReadingId] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [novels, setNovels] = useState([]);
  const [novelsLoading, setNovelsLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [pendingDelete, setPendingDelete] = useState(null);
  const [toDeleteId, setToDeleteId] = useState(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const uploadAbortRef = useRef(null);

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
    fetchNovels();
  }, []);

  const handleUpload = async (validationError, file) => {
    if (validationError) {
      toast.error(validationError.message);
      return;
    }
    if (!file) return;
    if (uploadAbortRef.current) uploadAbortRef.current.abort();
    const controller = new AbortController();
    uploadAbortRef.current = controller;
    setUploading(true);
    setProgress({ ratio: 0 });
    try {
      const result = await api.novels.upload(file, {
        signal: controller.signal,
        onProgress: (p) => setProgress(p),
      });
      toast.success(`「${result.title}」上传成功`);
      setUploadOpen(false);
      setSelectedId(result.id);
      setView('detail');
      await fetchNovels();
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      toast.error(err instanceof ApiError ? err.message : '上传失败');
    } finally {
      setUploading(false);
      setProgress(null);
    }
  };

  const handleBackToList = async () => {
    setSelectedId(null);
    setView('list');
    await fetchNovels();
  };

  const requestDelete = (id) => {
    setToDeleteId(id);
    setPendingDelete(novels.find((n) => n.id === id));
  };

  const confirmDelete = async () => {
    if (!toDeleteId) return;
    const id = toDeleteId;
    setPendingDelete(null);
    setToDeleteId(null);
    try {
      await api.novels.remove(id);
      toast.success('已删除');
      await fetchNovels();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  if (view === 'detail' && selectedId) {
    return (
      <div className="workbench-content">
        <NovelWorkbench
          key={selectedId}
          novelId={selectedId}
          models={models}
          onBack={handleBackToList}
          onStartReading={(id) => setReadingId(id)}
          onChanged={fetchNovels}
        />
        {readingId && (
          <NovelReader novelId={readingId} onBack={() => setReadingId(null)} />
        )}
        <ConfirmDialog
          open={!!pendingDelete}
          title="删除小说"
          message={`确定要删除「${pendingDelete?.title}」吗？所有章节、人物也会一起删除，此操作不可撤销。`}
          danger
          confirmText="删除"
          onCancel={() => {
            setPendingDelete(null);
            setToDeleteId(null);
          }}
          onConfirm={confirmDelete}
        />
      </div>
    );
  }

  const filtered = novels.filter((n) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      n.title.toLowerCase().includes(q) ||
      (n.author || '').toLowerCase().includes(q) ||
      (n.summary || '').toLowerCase().includes(q)
    );
  });

  return (
    <div className="workbench-content">
      <header className="page-header">
        <div className="page-header-text">
          <h1>我的项目</h1>
          <p>管理您所有的智能小说项目</p>
        </div>
        <button
          type="button"
          className="new-project-btn"
          onClick={() => setUploadOpen(true)}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" />
          </svg>
          新建项目
        </button>
      </header>

      {novels.length > 0 && (
        <div className="project-search-bar">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
            <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" />
          </svg>
          <input
            type="text"
            placeholder="搜索项目标题、作者或内容..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      )}

      {novelsLoading ? (
        <div className="loading-block">
          <div className="loading-spinner large"></div>
          <p>加载项目中...</p>
        </div>
      ) : novels.length === 0 ? (
        <div className="empty-projects">
          <svg width="56" height="56" viewBox="0 0 24 24" fill="none">
            <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="1.5" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <p>还没有任何项目</p>
          <span>点击右上角「新建项目」上传你的第一本小说</span>
          <button
            type="button"
            className="new-project-btn"
            onClick={() => setUploadOpen(true)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" />
            </svg>
            新建项目
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-projects">
          <p>没有匹配的项目</p>
          <span>尝试更换关键词</span>
        </div>
      ) : (
        <section className="project-grid">
          {filtered.map((novel) => (
            <NovelCard
              key={novel.id}
              novel={novel}
              onOpen={(id) => {
                setSelectedId(id);
                setView('detail');
              }}
              onStartReading={(id) => setReadingId(id)}
              onDelete={requestDelete}
            />
          ))}
        </section>
      )}

      <UploadModal
        open={uploadOpen}
        onClose={() => !uploading && setUploadOpen(false)}
        onUpload={handleUpload}
        uploading={uploading}
        progress={progress}
      />

      {readingId && <NovelReader novelId={readingId} onBack={() => setReadingId(null)} />}

      <ConfirmDialog
        open={!!pendingDelete}
        title="删除项目"
        message={`确定要删除「${pendingDelete?.title}」吗？所有章节、人物也会一起删除，此操作不可撤销。`}
        danger
        confirmText="删除"
        onCancel={() => {
          setPendingDelete(null);
          setToDeleteId(null);
        }}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
