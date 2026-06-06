import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { ConfirmDialog } from './Modal/ConfirmDialog.jsx';
import { useToast } from './Toast/ToastProvider.jsx';
import {
  buildSimpleRule,
  DEFAULT_EXTRA_RULE,
  NUMBER_TYPE_OPTIONS,
  PARSE_MODE,
  PREFIX_OPTIONS,
  PRESET_RULES,
  tryCompileRegex,
} from '../utils/regex.js';
import NovelReader from './NovelReader.jsx';

const DEFAULT_RULE = PRESET_RULES[0].value;

function StatusBadge({ status }) {
  if (status === 'parsed') {
    return <span className="status-badge status-parsed">已解析</span>;
  }
  if (status === 'pending') {
    return <span className="status-badge status-pending">待解析</span>;
  }
  return <span className="status-badge">{status}</span>;
}

function NovelListView({ novels, onOpen, onStartReading, onUpload, onDelete, uploading, progress }) {
  const [search, setSearch] = useState('');
  const filtered = novels.filter(
    (n) =>
      n.title.toLowerCase().includes(search.toLowerCase()) ||
      n.author.toLowerCase().includes(search.toLowerCase())
  );
  const fileRef = useRef(null);

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.txt')) {
      onUpload(new ApiError('仅支持 TXT 文件', 400, null), null);
      return;
    }
    onUpload(null, file);
  };

  return (
    <div className="novel-list-view">
      <input
        ref={fileRef}
        type="file"
        accept=".txt"
        onChange={handleFile}
        style={{ display: 'none' }}
      />
      <div className="list-header">
        <div className="search-box">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
            <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" />
          </svg>
          <input
            type="text"
            placeholder="搜索小说..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <button
          className="upload-btn"
          type="button"
          disabled={uploading}
          onClick={() => fileRef.current?.click()}
        >
          {uploading ? (
            <>
              <span className="loading-spinner small"></span>
              上传中 {Math.round((progress?.ratio || 0) * 100)}%
            </>
          ) : (
            <>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" />
              </svg>
              上传小说
            </>
          )}
        </button>
      </div>

      {uploading && progress && (
        <div className="upload-progress" role="progressbar" aria-valuenow={Math.round(progress.ratio * 100)}>
          <div className="upload-progress-bar" style={{ width: `${progress.ratio * 100}%` }} />
        </div>
      )}

      <div className="novel-cards">
        {filtered.length === 0 ? (
          <div className="empty-novels">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none">
              <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="2" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="2" />
            </svg>
            <p>{novels.length === 0 ? '暂无小说' : '没有匹配的小说'}</p>
            <span>点击上方按钮上传第一本小说</span>
          </div>
        ) : (
          filtered.map((novel) => (
            <div key={novel.id} className={`novel-card ${novel.chapter_count > 0 ? 'has-chapters' : ''}`}>
              <div className="novel-card-header">
                <div className="novel-icon-wrapper" onClick={() => onOpen(novel.id)}>
                  <div className="novel-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                      <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="2" />
                      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="2" />
                    </svg>
                  </div>
                  <StatusBadge status={novel.status} />
                </div>
                <div className="novel-card-actions">
                  {novel.chapter_count > 0 && (
                    <button
                      className="card-read-btn"
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onStartReading(novel.id);
                      }}
                      title="立即阅读"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" stroke="currentColor" strokeWidth="2" />
                        <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" stroke="currentColor" strokeWidth="2" />
                      </svg>
                    </button>
                  )}
                  <button
                    className="card-delete-btn"
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete?.(novel.id);
                    }}
                    title="删除"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" stroke="currentColor" strokeWidth="2" />
                    </svg>
                  </button>
                </div>
              </div>

              <div className="novel-card-body" onClick={() => onOpen(novel.id)}>
                <h3 className="novel-title">{novel.title}</h3>
                <p className="novel-author">作者：{novel.author}</p>
                <div className="novel-meta">
                  <span className="chapter-count">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M9 12h6M9 16h6M17 21H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                        stroke="currentColor"
                        strokeWidth="2"
                      />
                    </svg>
                    {novel.chapter_count} 章
                  </span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ChapterContentPanel({ chapter, onClose }) {
  if (!chapter) return null;
  return (
    <div className="chapter-content-panel">
      <div className="content-header">
        <h3>{chapter.title}</h3>
        <button className="close-btn" type="button" onClick={onClose}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
      </div>
      <div className="content-body">
        <p style={{ whiteSpace: 'pre-wrap' }}>{chapter.content || '暂无内容'}</p>
      </div>
    </div>
  );
}

function ChapterPreviewPanel({ preview }) {
  if (!preview) {
    return (
      <div className="chapter-preview-panel empty">
        <div className="empty-doc-icon" aria-hidden>
          <svg width="42" height="42" viewBox="0 0 24 24" fill="none">
            <path
              d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path d="M14 2v6h6" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </div>
        <p className="empty-title">准备就绪</p>
        <p className="empty-sub">点击「预览」可在此查看章节拆分效果</p>
      </div>
    );
  }
  if (preview.error) {
    return (
      <div className="chapter-preview-panel error">
        <p className="empty-title">预览失败</p>
        <p className="empty-sub">{preview.error}</p>
      </div>
    );
  }
  const items = preview.preview || [];
  return (
    <div className="chapter-preview-panel">
      <div className="preview-summary">
        共匹配 <strong>{preview.chapters_found}</strong> 个章节
      </div>
      {items.length > 0 && (
        <ol className="preview-full-list">
          {items.map((c) => (
            <li key={c.chapter_number}>
              <span className="preview-num">#{c.chapter_number}</span>
              <span className="preview-title">{c.title}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const initialState = {
  novel: null,
  loading: false,
  error: null,
  parseMode: PARSE_MODE.SIMPLE,
  parseRule: DEFAULT_RULE,
  prefix: PREFIX_OPTIONS[0].value,
  numberType: 'mixed',
  extraRule: DEFAULT_EXTRA_RULE,
  parsing: false,
  parseResult: null,
  preview: null,
  previewing: false,
  parsingFixed: false,
  selectedChapter: null,
  chapterContent: null,
  loadingChapter: false,
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
        selectedChapter: null,
        chapterContent: null,
        parseResult: null,
        preview: null,
      };
    case 'LOAD_ERR':
      return { ...state, loading: false, error: action.error };
    case 'SET_RULE':
      return { ...state, parseRule: action.rule, parseResult: null, preview: null };
    case 'SET_MODE':
      return { ...state, parseMode: action.mode, parseResult: null, preview: null };
    case 'SET_PREFIX':
      return { ...state, prefix: action.prefix, parseResult: null, preview: null };
    case 'SET_NUMBER_TYPE':
      return { ...state, numberType: action.numberType, parseResult: null, preview: null };
    case 'SET_EXTRA_RULE':
      return { ...state, extraRule: action.extraRule, parseResult: null, preview: null };
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
    case 'CHAPTER_START':
      return { ...state, loadingChapter: true, chapterContent: null };
    case 'CHAPTER_OK':
      return { ...state, loadingChapter: false, chapterContent: action.chapter };
    case 'CHAPTER_ERR':
      return { ...state, loadingChapter: false, chapterContent: { content: '', error: action.error } };
    case 'CLOSE_CHAPTER':
      return { ...state, selectedChapter: null, chapterContent: null };
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

function NovelDetailView({
  novelId,
  onBack,
  onStartReading,
  onChanged,
  onDeleted,
}) {
  const toast = useToast();
  const [state, dispatch] = useReducer(detailReducer, initialState);
  const [chunkSize, setChunkSize] = useState(5000);
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

  // 当前生效的正则（按模式计算）
  const activeRule = useMemo(() => {
    if (state.parseMode === PARSE_MODE.SIMPLE) {
      return buildSimpleRule({
        prefix: state.prefix,
        numberType: state.numberType,
        extraRule: state.extraRule,
      });
    }
    return state.parseRule;
  }, [
    state.parseMode,
    state.prefix,
    state.numberType,
    state.extraRule,
    state.parseRule,
  ]);

  const requireRule = (action) => {
    if (state.parseMode === PARSE_MODE.SIMPLE) {
      if (!state.extraRule.trim()) {
        toast.error('请填写附加规则');
        return false;
      }
      return true;
    }
    if (!state.parseRule.trim()) {
      toast.error('请输入解析规则');
      return false;
    }
    const compile = tryCompileRegex(state.parseRule);
    if (!compile.ok) {
      toast.error(`无效正则: ${compile.error}`);
      return false;
    }
    return true;
  };

  const handlePreview = async () => {
    if (!requireRule()) return;
    dispatch({ type: 'PREVIEW_START' });
    try {
      const preview = await api.novels.parsePreview(novelId, activeRule);
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
    if (!requireRule()) return;
    dispatch({ type: 'PARSE_START' });
    try {
      const result = await api.novels.parse(novelId, activeRule);
      dispatch({ type: 'PARSE_OK', result });
      if (result.success) {
        toast.success(result.message);
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

  const handleChapterClick = async (chapter) => {
    dispatch({ type: 'CHAPTER_START' });
    try {
      const data = await api.novels.chapter(novelId, chapter.id);
      dispatch({ type: 'CHAPTER_OK', chapter: { ...chapter, content: data.content } });
    } catch (err) {
      dispatch({ type: 'CHAPTER_ERR', error: err.message });
    }
  };

  if (state.loading) {
    return (
      <div className="novel-detail loading">
        <div className="loading-spinner large"></div>
        <p>加载中...</p>
      </div>
    );
  }
  if (state.error || !state.novel) {
    return (
      <div className="novel-detail error">
        <p>{state.error || '小说不存在'}</p>
        <button type="button" className="btn btn-primary" onClick={onBack}>
          返回列表
        </button>
      </div>
    );
  }

  return (
    <div className="novel-detail">
      <div className="detail-header">
        <button className="back-btn" type="button" onClick={onBack}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        {state.editing ? (
          <div className="edit-form">
            <input
              type="text"
              value={state.editTitle}
              onChange={(e) => dispatch({ type: 'EDIT_FIELD', patch: { editTitle: e.target.value } })}
              placeholder="小说标题"
            />
            <input
              type="text"
              value={state.editAuthor}
              onChange={(e) => dispatch({ type: 'EDIT_FIELD', patch: { editAuthor: e.target.value } })}
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
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="2" />
            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
      </div>

      <div className="parse-section">
        <div className="parse-section-header">
          <h3>
            章节解析
            {state.novel.chapters?.length > 0 && (
              <span className="chapter-count">{state.novel.chapters.length} 章</span>
            )}
          </h3>
          {state.novel.chapters?.length > 0 && (
            <button
              className="start-reading-btn"
              type="button"
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

        <div className="parse-config">
          <label className="radio-row">
            <input
              type="radio"
              name="parse-mode"
              checked={state.parseMode === PARSE_MODE.SIMPLE}
              onChange={() => dispatch({ type: 'SET_MODE', mode: PARSE_MODE.SIMPLE })}
            />
            <span>简单规则</span>
            <span className="check-flag">
              <input
                type="checkbox"
                checked
                readOnly
                tabIndex={-1}
                aria-label="行首标识启用"
              />
              <span>行首标识</span>
            </span>
            <select
              className="config-select"
              value={state.prefix}
              onChange={(e) => dispatch({ type: 'SET_PREFIX', prefix: e.target.value })}
              disabled={state.parseMode !== PARSE_MODE.SIMPLE}
            >
              {PREFIX_OPTIONS.map((opt) => (
                <option key={`p-${opt.label}`} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <select
              className="config-select"
              value={state.numberType}
              onChange={(e) =>
                dispatch({ type: 'SET_NUMBER_TYPE', numberType: e.target.value })
              }
              disabled={state.parseMode !== PARSE_MODE.SIMPLE}
            >
              {NUMBER_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <select
              className="config-select"
              value={state.extraRule}
              onChange={(e) =>
                dispatch({ type: 'SET_EXTRA_RULE', extraRule: e.target.value })
              }
              disabled={state.parseMode !== PARSE_MODE.SIMPLE}
              title="附加规则预设"
            >
              <option value={DEFAULT_EXTRA_RULE}>[章回卷节部]</option>
              <option value="">[不使用附加规则]</option>
              <option value={DEFAULT_EXTRA_RULE}>[章回卷节部+特殊章]</option>
            </select>
          </label>

          <div className="sub-row">
            <span className="inline-label">附加规则</span>
            <input
              type="text"
              className="config-input"
              value={state.extraRule}
              onChange={(e) =>
                dispatch({ type: 'SET_EXTRA_RULE', extraRule: e.target.value })
              }
              placeholder="^\\s*(序章|序幕|序[1-9]|序曲|楔子|前言|后记|尾声|番外|最终章)"
              disabled={state.parseMode !== PARSE_MODE.SIMPLE}
            />
          </div>

          <label className="radio-row">
            <input
              type="radio"
              name="parse-mode"
              checked={state.parseMode === PARSE_MODE.REGEX}
              onChange={() => dispatch({ type: 'SET_MODE', mode: PARSE_MODE.REGEX })}
            />
            <span>正则表达式</span>
            <input
              type="text"
              className="config-input"
              value={state.parseRule}
              onChange={(e) => dispatch({ type: 'SET_RULE', rule: e.target.value })}
              placeholder="^\\s*(\\d+)\\s+(.+)$"
              disabled={state.parseMode !== PARSE_MODE.REGEX}
            />
          </label>

          <div className="parse-actions-row">
            <div className="preview-toggle">
              <span className="eye-icon" aria-hidden>◉</span>
              <span>章节预览</span>
              {state.preview && !state.preview.error && (
                <span className="preview-count">
                  {state.preview.chapters_found} 个
                </span>
              )}
            </div>
            <button
              className="parse-btn"
              type="button"
              onClick={handlePreview}
              disabled={state.previewing}
            >
              {state.previewing ? <span className="loading-spinner"></span> : '▶ 预览'}
            </button>
          </div>
        </div>

        <ChapterPreviewPanel preview={state.preview} />

        <div className="parse-secondary">
          <div className="rule-input-group">
            <label className="inline-label">固定字数：</label>
            <select
              value={chunkSize}
              onChange={(e) => setChunkSize(Number(e.target.value))}
            >
              <option value={3000}>3000字</option>
              <option value={5000}>5000字</option>
              <option value={8000}>8000字</option>
              <option value={10000}>10000字</option>
            </select>
            <button
              className="parse-btn"
              type="button"
              onClick={handleParseFixed}
              disabled={state.parsingFixed}
            >
              {state.parsingFixed ? <span className="loading-spinner"></span> : '按字数切分'}
            </button>
            <button
              className="parse-btn primary"
              type="button"
              onClick={handleParse}
              disabled={state.parsing}
            >
              {state.parsing ? <span className="loading-spinner"></span> : '解析'}
            </button>
          </div>
        </div>

        {state.parseResult && (
          <div className={`parse-result ${state.parseResult.success ? 'success' : 'error'}`}>
            <span>{state.parseResult.message}</span>
          </div>
        )}
      </div>

      <div className="chapters-section">
        <h3>
          章节列表
          {state.novel.chapters && (
            <span className="chapter-count">{state.novel.chapters.length} 章</span>
          )}
        </h3>
        {state.novel.chapters?.length > 0 ? (
          <div className="chapters-grid">
            {state.novel.chapters.map((chapter) => (
              <button
                key={chapter.id}
                type="button"
                className={`chapter-item ${state.selectedChapter?.id === chapter.id ? 'selected' : ''}`}
                onClick={() => handleChapterClick(chapter)}
              >
                <span className="chapter-number">{chapter.chapter_number}</span>
                <span className="chapter-title">{chapter.title}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="no-chapters">
            <p>暂无章节，请先设置解析规则并解析</p>
          </div>
        )}
      </div>

      {state.selectedChapter && (
        <ChapterContentPanel
          chapter={state.chapterContent}
          onClose={() => dispatch({ type: 'CLOSE_CHAPTER' })}
        />
      )}
    </div>
  );
}

export function NovelPanel({ novels, refetch }) {
  const toast = useToast();
  const [view, setView] = useState('list');
  const [selectedId, setSelectedId] = useState(null);
  const [readingId, setReadingId] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [toDeleteId, setToDeleteId] = useState(null);
  const uploadAbortRef = useRef(null);

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
      setSelectedId(result.id);
      setView('detail');
      await refetch();
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
    await refetch();
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
      await refetch();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  return (
    <div className="novels-content">
      {view === 'detail' && selectedId ? (
        <NovelDetailView
          key={selectedId}
          novelId={selectedId}
          onBack={handleBackToList}
          onStartReading={(id) => setReadingId(id)}
          onChanged={refetch}
          onDeleted={handleBackToList}
        />
      ) : (
        <NovelListView
          novels={novels}
          uploading={uploading}
          progress={progress}
          onOpen={(id) => {
            setSelectedId(id);
            setView('detail');
          }}
          onStartReading={(id) => setReadingId(id)}
          onUpload={handleUpload}
          onDelete={requestDelete}
        />
      )}
      {readingId && (
        <NovelReader
          novelId={readingId}
          onBack={() => setReadingId(null)}
        />
      )}
      <ConfirmDialog
        open={!!pendingDelete}
        title="删除小说"
        message={`确定要删除「${pendingDelete?.title}」吗？所有章节也会一起删除，此操作不可撤销。`}
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
