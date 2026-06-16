import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { tryCompileRegex } from '../utils/regex.js';
import { useToast } from './Toast/ToastProvider.jsx';
import { EnrichmentSidePanel } from './enrichment/EnrichmentSidePanel.jsx';
import { SuggestionHistoryModal } from './enrichment/SuggestionHistoryModal.jsx';
import { MergedReader } from './enrichment/MergedReader.jsx';
import { SideBySideReader } from './enrichment/SideBySideReader.jsx';
import { HighlightedReader } from './enrichment/HighlightedReader.jsx';
import '../App.css';

const READING_PRESETS = [
  { name: '默认', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#f8f5f0', color: '#333', sidebarBg: '#fff', sidebarColor: '#333' },
  { name: '护眼', fontSize: 18, lineHeight: 2, letterSpacing: 1, background: '#f0e6d3', color: '#5a4a3a', sidebarBg: '#e8dcc8', sidebarColor: '#4a3a2a' },
  { name: '深夜', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#1a1a1a', color: '#b0b0b0', sidebarBg: '#252525', sidebarColor: '#b0b0b0' },
  { name: '纯黑', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#000', color: '#fff', sidebarBg: '#111', sidebarColor: '#fff' },
  { name: '书籍', fontSize: 16, lineHeight: 2.2, letterSpacing: 0.5, background: '#faf8f5', color: '#2c2c2c', sidebarBg: '#f0ebe3', sidebarColor: '#2c2c2c' },
];

// 把章节内容切成 [{type, text, matchIndex, isCurrent}] 段,
// 供 content-text 渲染出高亮匹配. matchIndex 用于 "上一个/下一个" 跳转.
function buildContentSegments(content, matches, currentIndex) {
  if (!content) return [];
  if (!matches || matches.length === 0) {
    return [{ type: 'plain', text: content }];
  }
  const sorted = [...matches].sort((a, b) => a.index - b.index);
  const segments = [];
  let cursor = 0;
  sorted.forEach((m, i) => {
    if (m.index < cursor) {
      // 重叠 / 越界, 跳过
      return;
    }
    if (m.index > cursor) {
      segments.push({ type: 'plain', text: content.slice(cursor, m.index) });
    }
    segments.push({
      type: 'match',
      text: content.slice(m.index, m.index + m.length),
      matchIndex: i,
      isCurrent: i === currentIndex,
    });
    cursor = m.index + m.length;
  });
  if (cursor < content.length) {
    segments.push({ type: 'plain', text: content.slice(cursor) });
  }
  return segments;
}

function NovelReader({ novelId, onBack, models: externalModels, onGoToWorkbench }) {
  const toast = useToast();
  const [novel, setNovel] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingChapter, setLoadingChapter] = useState(false);
  const [error, setError] = useState(null);
  // v0.2: 加料信息仅供侧边面板展示; 不再切换 chapters.content 来源
  const [enrichmentMap, setEnrichmentMap] = useState({}); // chapterId -> enrichment detail
  // v0.2: 侧边 AI 加料面板
  const [showEnrichmentPanel, setShowEnrichmentPanel] = useState(false);
  // v0.2.1: 阅读器内显示模式 ('original' | 'merged' | 'sidebyside' | 'highlight')
  // - original: 纯 chapters.content
  // - merged: 段落级合并阅读 (原文+改写交替)
  // - sidebyside: 并排对比
  // - highlight: 字符级 diff 高亮叠加
  const [displayMode, setDisplayMode] = useState('original');
  const [previewSegments, setPreviewSegments] = useState(null);
  const [previewTruncated, setPreviewTruncated] = useState(false);
  const [selfModels, setSelfModels] = useState([]);
  const [selectedModelId, setSelectedModelId] = useState(null);
  const [showHistoryFor, setShowHistoryFor] = useState(null);
  const effectiveModels =
    externalModels && externalModels.length > 0 ? externalModels : selfModels;
  const enabledChatModels = (effectiveModels || []).filter(
    (m) => (m.capability || 'chat') === 'chat' && m.enabled
  );

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const [presetIndex, setPresetIndex] = useState(0);
  const [fontSize, setFontSize] = useState(18);
  const [lineHeight, setLineHeight] = useState(1.8);
  const [letterSpacing, setLetterSpacing] = useState(0);
  const [background, setBackground] = useState('#f8f5f0');
  const [textColor, setTextColor] = useState('#333');
  const [sidebarBg, setSidebarBg] = useState('#fff');
  const [sidebarColor, setSidebarColor] = useState('#333');

  const [findText, setFindText] = useState('');
  const [replaceText, setReplaceText] = useState('');
  const [findResults, setFindResults] = useState([]);
  const [currentResultIndex, setCurrentResultIndex] = useState(-1);
  const [showFindPanel, setShowFindPanel] = useState(false);

  // 替换/编辑后的"脏数据"状态: 用于在 find 面板显示 "保存修改" 按钮
  const [contentDirty, setContentDirty] = useState(false);
  // 保存请求进行中, 防重复点击
  const [saving, setSaving] = useState(false);

  // 编辑模式: 直接编辑章节标题 / 正文
  const [editMode, setEditMode] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');

  const abortRef = useRef(null);
  const contentScrollRef = useRef(null);
  const highlightRefs = useRef({}); // matchIndex -> HTMLElement
  const [scrollRatio, setScrollRatio] = useState(0);

  useEffect(() => {
    abortRef.current?.abort?.();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const data = await api.novels.detail(novelId, { signal: controller.signal });
        setNovel(data);
        setChapters(data.chapters || []);
        setCurrentIndex(0);
        // 切换小说时, 关闭高亮预览
        setPreviewSegments(null);
        setPreviewTruncated(false);
      } catch (err) {
        if (err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : '加载失败');
      } finally {
        setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [novelId]);

  // 拉模型 (仅当外部未传时)
  useEffect(() => {
    if (externalModels && externalModels.length > 0) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api.models.list();
        if (!cancelled) {
          setSelfModels(data.configs || []);
        }
      } catch {
        // 静默
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [externalModels]);

  // 默认选中第一个 enabled chat 模型
  useEffect(() => {
    if (selectedModelId) {
      const still = enabledChatModels.some((m) => m.id === selectedModelId);
      if (still) return;
    }
    setSelectedModelId(enabledChatModels[0]?.id || null);
  }, [enabledChatModels, selectedModelId]);

  useEffect(() => {
    if (chapters.length === 0) return;
    if (currentIndex >= chapters.length) {
      setCurrentIndex(0);
      return;
    }
    abortRef.current?.abort?.();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoadingChapter(true);
    setContent('');
    setFindResults([]);
    setCurrentResultIndex(-1);
    // 切换章节: 退出编辑模式, 丢弃未保存的本地改动
    setEditMode(false);
    setContentDirty(false);
    highlightRefs.current = {};
    // 切换章节时切回原始视图, 并清掉高亮 preview
    setDisplayMode('original');
    setPreviewSegments(null);
    setPreviewTruncated(false);
    (async () => {
      try {
        const data = await api.novels.chapter(novelId, chapters[currentIndex].id, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setContent(data.content || '');
      } catch (err) {
        if (err.name === 'AbortError') return;
        setContent(`加载失败: ${err instanceof ApiError ? err.message : err.message}`);
      } finally {
        if (!controller.signal.aborted) setLoadingChapter(false);
      }
    })();
    return () => controller.abort();
  }, [currentIndex, chapters, novelId]);

  // 拉取所有章节的加料详情(用于「加料版」切换),尽量轻量
  useEffect(() => {
    if (chapters.length === 0) return;
    let cancelled = false;
    const controller = new AbortController();
    (async () => {
      // 用 listProgress 一次拿到整本的进度与每章的 rewrite 状态
      try {
        const data = await api.enrichment.listProgress(novelId, { signal: controller.signal });
        if (cancelled || !data?.items) return;
        // 同时按需拉取每个章节的加料详情
        const items = data.items;
        const needDetail = items.filter(
          (it) => it.rewrite_status === 'done' && !enrichmentMap[it.chapter_id]
        );
        if (needDetail.length === 0) return;
        await Promise.all(
          needDetail.map(async (it) => {
            try {
              const detail = await api.enrichment.getDetail(it.chapter_id, {
                signal: controller.signal,
              });
              if (cancelled) return;
              setEnrichmentMap((prev) => ({ ...prev, [it.chapter_id]: detail }));
            } catch {
              // 单章失败不影响其它
            }
          })
        );
      } catch {
        // 后端未启用或暂无数据 — 静默忽略
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
    // 仅在 chapters/novelId 变化时重新拉
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelId, chapters.length]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      // 优先关闭打开的面板，再退到关闭阅读器
      if (e.key === 'Escape') {
        if (displayMode !== 'original') {
          setDisplayMode('original');
          setPreviewSegments(null);
          return;
        }
        if (showEnrichmentPanel) {
          setShowEnrichmentPanel(false);
          return;
        }
        if (showFindPanel) {
          setShowFindPanel(false);
          return;
        }
        if (showSettings) {
          setShowSettings(false);
          return;
        }
        onBack?.();
        return;
      }
      if (e.key === 'ArrowLeft') setCurrentIndex((i) => Math.max(0, i - 1));
      if (e.key === 'ArrowRight') setCurrentIndex((i) => Math.min(chapters.length - 1, i + 1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [chapters.length, onBack, showFindPanel, showSettings, showEnrichmentPanel, displayMode]);

  const handlePresetChange = (index) => {
    const preset = READING_PRESETS[index];
    setPresetIndex(index);
    setFontSize(preset.fontSize);
    setLineHeight(preset.lineHeight);
    setLetterSpacing(preset.letterSpacing);
    setBackground(preset.background);
    setTextColor(preset.color);
    setSidebarBg(preset.sidebarBg);
    setSidebarColor(preset.sidebarColor);
  };

  const handleFind = () => {
    if (!findText) {
      setFindResults([]);
      setCurrentResultIndex(-1);
      return;
    }
    const compile = tryCompileRegex(findText);
    if (!compile.ok) {
      toast.error(`无效正则: ${compile.error}`);
      return;
    }
    const re = new RegExp(findText, 'gi');
    const matches = [];
    let m;
    while ((m = re.exec(currentContent)) !== null) {
      matches.push({ index: m.index, length: m[0].length, text: m[0] });
    }
    setFindResults(matches);
    setCurrentResultIndex(matches.length > 0 ? 0 : -1);
    if (matches.length === 0) toast.info('没有匹配结果');
  };

  const handleReplace = () => {
    if (!findText || currentResultIndex < 0) return;
    const result = findResults[currentResultIndex];
    const next =
      content.substring(0, result.index) +
      replaceText +
      content.substring(result.index + result.length);
    setContent(next);
    setContentDirty(true);
    handleFind();
  };

  const handleReplaceAll = () => {
    if (!findText) return;
    try {
      const re = new RegExp(findText, 'g');
      const next = content.replace(re, replaceText);
      setContent(next);
      setContentDirty(true);
      setFindResults([]);
      setCurrentResultIndex(-1);
      toast.success('已替换');
    } catch (err) {
      toast.error(`无效正则: ${err.message}`);
    }
  };

  // 把"阅读态"的修改(替换/全部替换)保存到后端
  const handleSaveChanges = async () => {
    const chapter = chapters[currentIndex];
    if (!chapter) return;
    if (!contentDirty) {
      toast.info('没有需要保存的修改');
      return;
    }
    setSaving(true);
    try {
      const updated = await api.novels.updateChapter(novelId, chapter.id, {
        content,
      });
      setChapters((cs) =>
        cs.map((c) => (c.id === updated.id ? { ...c, ...updated } : c))
      );
      setContentDirty(false);
      setFindResults([]);
      setCurrentResultIndex(-1);
      toast.success('已保存到服务器');
    } catch (err) {
      toast.error(
        `保存失败: ${err instanceof ApiError ? err.message : err.message}`
      );
    } finally {
      setSaving(false);
    }
  };

  // ===== 编辑模式 =====
  const startEdit = () => {
    const chapter = chapters[currentIndex];
    if (!chapter) return;
    setEditTitle(chapter.title || '');
    setEditContent(content || '');
    setEditMode(true);
    setShowFindPanel(false);
    setShowSettings(false);
  };

  const cancelEdit = () => {
    if (saving) return;
    setEditMode(false);
  };

  const saveEdit = async () => {
    const chapter = chapters[currentIndex];
    if (!chapter) return;
    if (!editTitle.trim()) {
      toast.error('章节标题不能为空');
      return;
    }
    setSaving(true);
    try {
      const updated = await api.novels.updateChapter(novelId, chapter.id, {
        title: editTitle.trim(),
        content: editContent,
      });
      // 同步本地章节列表中的标题
      setChapters((cs) =>
        cs.map((c) => (c.id === updated.id ? { ...c, ...updated } : c))
      );
      setContent(updated.content || '');
      setContentDirty(false);
      setFindResults([]);
      setCurrentResultIndex(-1);
      setEditMode(false);
      toast.success('已保存');
    } catch (err) {
      toast.error(
        `保存失败: ${err instanceof ApiError ? err.message : err.message}`
      );
    } finally {
      setSaving(false);
    }
  };

  const scrollToResult = (index) => {
    setCurrentResultIndex(index);
    const container = contentScrollRef.current;
    if (!container) return;
    // 高亮元素渲染完后再计算位置
    requestAnimationFrame(() => {
      const el = highlightRefs.current[index];
      if (!el) {
        // 兜底: 退回到比例估算
        const result = findResults[index];
        if (!result) return;
        const totalLength = content.length || 1;
        const ratio = result.index / totalLength;
        const targetTop =
          container.scrollHeight * ratio - container.clientHeight * 0.3;
        container.scrollTo({
          top: Math.max(0, targetTop),
          behavior: 'smooth',
        });
        return;
      }
      const elRect = el.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      const offset =
        elRect.top - containerRect.top + container.scrollTop -
        container.clientHeight * 0.3;
      container.scrollTo({ top: Math.max(0, offset), behavior: 'smooth' });
    });
  };

  // 用于渲染时建立 matchIndex -> HTMLElement 映射
  const setHighlightRef = (matchIndex) => (el) => {
    if (el) {
      highlightRefs.current[matchIndex] = el;
    } else {
      delete highlightRefs.current[matchIndex];
    }
  };

  // 当前章节的加料版本(若有): v0.2 不再直接替换正文, 仅用于侧边面板展示
  const currentEnrichment = useMemo(() => {
    const ch = chapters[currentIndex];
    if (!ch) return null;
    return enrichmentMap[ch.id] || null;
  }, [chapters, currentIndex, enrichmentMap]);

  const currentContent = useMemo(() => {
    // v0.2: 正文始终来自 chapters.content; 加料由用户在侧栏一键应用
    return content;
  }, [content]);

  // 当处于"高亮预览"模式时, 正文以 diff segments 渲染
  const contentSegments = useMemo(() => {
    if (displayMode === 'highlight' && previewSegments && previewSegments.length > 0) {
      // 把 diff 段切成 [{type, text, isCurrent}]; 不做查找高亮叠加
      return previewSegments.map((s, i) => ({
        type: s.type === 'added' || s.type === 'removed' ? s.type : 'plain',
        text: s.text,
        // 保留 isCurrent 用于查找高亮 (未使用)
        isCurrent: false,
        matchIndex: -1,
        // 区分 added/removed/unchanged 渲染样式
        diffType: s.type,
      }));
    }
    return buildContentSegments(currentContent, findResults, currentResultIndex);
  }, [displayMode, previewSegments, currentContent, findResults, currentResultIndex]);

  const styles = useMemo(
    () => ({
      '--reader-bg': background,
      '--reader-color': textColor,
      '--reader-font-size': `${fontSize}px`,
      '--reader-line-height': lineHeight,
      '--reader-letter-spacing': `${letterSpacing}px`,
      '--sidebar-bg': sidebarBg,
      '--sidebar-color': sidebarColor,
    }),
    [background, textColor, fontSize, lineHeight, letterSpacing, sidebarBg, sidebarColor]
  );

  // 章节字数与预估阅读时长（中文按 400 字/分钟）
  const contentLength = useMemo(() => {
    if (!currentContent) return 0;
    // 去除空白字符后按字符数统计
    return currentContent.replace(/\s+/g, '').length;
  }, [currentContent]);

  const readMinutes = useMemo(() => {
    if (!contentLength) return 0;
    return Math.max(1, Math.round(contentLength / 400));
  }, [contentLength]);

  if (loading) {
    return (
      <div className="novel-reader loading">
        <div className="loading-spinner large"></div>
        <p>加载中...</p>
      </div>
    );
  }

  if (error || !novel) {
    return (
      <div className="novel-reader error">
        <p>{error || '小说不存在'}</p>
        <button type="button" className="btn btn-primary" onClick={onBack}>
          返回列表
        </button>
      </div>
    );
  }

  return (
    <div className="novel-reader" style={styles}>
      <div className="reader-toolbar">
        <button className="toolbar-btn back-btn" type="button" onClick={onBack} title="返回">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <div className="toolbar-title-block">
          <span className="reader-title">{novel.title}</span>
          <span className="reader-subtitle">
            {chapters[currentIndex]?.title || ''}
          </span>
        </div>
        <div className="toolbar-progress" aria-hidden="true">
          <div className="toolbar-progress-fill" style={{ width: `${Math.round(scrollRatio * 100)}%` }} />
        </div>
        <div className="toolbar-actions">
          <button
            className={`toolbar-btn ${showEnrichmentPanel ? 'active' : ''}`}
            type="button"
            onClick={() => setShowEnrichmentPanel((v) => !v)}
            title="AI 加料"
            aria-pressed={showEnrichmentPanel}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 2l2.39 4.84L19.5 7.5l-3.6 3.78L17 16.5l-5-2.55L7 16.5l1.1-5.22L4.5 7.5l5.11-.66L12 2z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinejoin="round"
              />
              <path
                d="M5 19h14M5 22h10"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
            AI 加料
          </button>
          <button
            className={`toolbar-btn ${editMode ? 'active' : ''}`}
            type="button"
            onClick={() => (editMode ? cancelEdit() : startEdit())}
            title={editMode ? '取消编辑' : '编辑章节'}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="2" />
              <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
          <button
            className={`toolbar-btn ${showFindPanel ? 'active' : ''}`}
            type="button"
            onClick={() => setShowFindPanel(!showFindPanel)}
            title="查找替换"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
              <path d="M21 21l-4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          <button
            className={`toolbar-btn ${showSettings ? 'active' : ''}`}
            type="button"
            onClick={() => setShowSettings(!showSettings)}
            title="设置"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>

      {showSettings && (
        <div className="reader-settings-panel">
          <div className="settings-header">
            <h3>阅读设置</h3>
            <button type="button" onClick={() => setShowSettings(false)}>×</button>
          </div>
          <div className="settings-section">
            <label>预设主题</label>
            <div className="preset-buttons">
              {READING_PRESETS.map((preset, index) => (
                <button
                  key={index}
                  type="button"
                  className={`preset-btn ${presetIndex === index ? 'active' : ''}`}
                  onClick={() => handlePresetChange(index)}
                  style={{ background: preset.background, color: preset.color }}
                >
                  {preset.name}
                </button>
              ))}
            </div>
          </div>
          <div className="settings-section">
            <label>字体大小: {fontSize}px</label>
            <input type="range" min="12" max="28" value={fontSize} onChange={(e) => setFontSize(Number(e.target.value))} />
          </div>
          <div className="settings-section">
            <label>行间距: {lineHeight}</label>
            <input type="range" min="1.2" max="3" step="0.1" value={lineHeight} onChange={(e) => setLineHeight(Number(e.target.value))} />
          </div>
          <div className="settings-section">
            <label>字符间距: {letterSpacing}px</label>
            <input type="range" min="0" max="5" step="0.5" value={letterSpacing} onChange={(e) => setLetterSpacing(Number(e.target.value))} />
          </div>
          <div className="settings-section">
            <label>背景色</label>
            <div className="color-options">
              {['#f8f5f0', '#f0e6d3', '#e8f4e8', '#1a1a1a', '#000'].map((c) => (
                <button key={c} type="button" className="color-btn" style={{ background: c }} onClick={() => setBackground(c)} />
              ))}
            </div>
          </div>
          <div className="settings-section">
            <label>文字色</label>
            <div className="color-options">
              {['#333', '#5a4a3a', '#2c5f2c', '#b0b0b0', '#fff'].map((c) => (
                <button key={c} type="button" className="color-btn" style={{ background: c }} onClick={() => setTextColor(c)} />
              ))}
            </div>
          </div>
        </div>
      )}

      {showFindPanel && (
        <div className="reader-find-panel">
          <div className="find-header">
            <h3>查找替换</h3>
            <button type="button" onClick={() => setShowFindPanel(false)}>×</button>
          </div>
          <div className="find-row">
            <input
              type="text"
              placeholder="查找内容（支持正则）"
              value={findText}
              onChange={(e) => setFindText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleFind();
                if (e.key === 'Escape') setShowFindPanel(false);
              }}
            />
            <button type="button" className="btn btn-primary" onClick={handleFind}>查找</button>
          </div>
          <div className="find-row">
            <input
              type="text"
              placeholder="替换为"
              value={replaceText}
              onChange={(e) => setReplaceText(e.target.value)}
            />
            <button type="button" className="btn" onClick={handleReplace}>替换</button>
            <button type="button" className="btn" onClick={handleReplaceAll}>全部替换</button>
          </div>
          {findResults.length > 0 && (
            <div className="find-results-info">
              找到 {findResults.length} 个匹配
              <div className="result-nav">
                <button
                  type="button"
                  disabled={currentResultIndex <= 0}
                  onClick={() => scrollToResult(currentResultIndex - 1)}
                >
                  上一个
                </button>
                <span>
                  {currentResultIndex + 1} / {findResults.length}
                </span>
                <button
                  type="button"
                  disabled={currentResultIndex >= findResults.length - 1}
                  onClick={() => scrollToResult(currentResultIndex + 1)}
                >
                  下一个
                </button>
              </div>
            </div>
          )}
          {contentDirty && (
            <div className="find-save-bar">
              <span className="dirty-hint">⚠ 当前有未保存的替换</span>
              <button
                type="button"
                className="btn btn-save"
                onClick={handleSaveChanges}
                disabled={saving}
              >
                {saving ? '保存中…' : '保存修改'}
              </button>
            </div>
          )}
        </div>
      )}

      <div className="reader-main">
        <div className={`reader-sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
          <div className="sidebar-header">
            <h3>目录</h3>
            <button type="button" className="collapse-btn" onClick={() => setSidebarCollapsed(!sidebarCollapsed)}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                {sidebarCollapsed ? (
                  <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" />
                ) : (
                  <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" />
                )}
              </svg>
            </button>
          </div>
          {!sidebarCollapsed && (
            <div className="chapter-list">
              {chapters.length === 0 ? (
                <div className="no-chapters">暂无章节</div>
              ) : (
                chapters.map((chapter, index) => (
                  <button
                    key={chapter.id}
                    type="button"
                    className={`chapter-item ${currentIndex === index ? 'active' : ''}`}
                    onClick={() => setCurrentIndex(index)}
                  >
                    <span className="chapter-num">{chapter.chapter_number}</span>
                    <span className="chapter-title">{chapter.title}</span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        <div className="reader-content">
          {editMode ? (
            <div className="reader-edit-panel">
              <div className="edit-panel-header">
                <h3>编辑章节</h3>
                <button
                  type="button"
                  className="edit-close-btn"
                  onClick={cancelEdit}
                  disabled={saving}
                  title="关闭"
                >
                  ×
                </button>
              </div>
              <div className="edit-form-body">
                <label className="edit-label">
                  <span>章节标题</span>
                  <input
                    type="text"
                    className="edit-title-input"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    placeholder="章节标题"
                    disabled={saving}
                  />
                </label>
                <label className="edit-label">
                  <span>正文</span>
                  <textarea
                    className="edit-content-textarea"
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    placeholder="章节正文"
                    disabled={saving}
                    rows={24}
                  />
                </label>
                <div className="edit-meta">
                  <span>
                    字数 {editContent.replace(/\s+/g, '').length.toLocaleString()}
                  </span>
                </div>
              </div>
              <div className="edit-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={saveEdit}
                  disabled={saving || !editTitle.trim()}
                >
                  {saving ? '保存中…' : '保存'}
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={cancelEdit}
                  disabled={saving}
                >
                  取消
                </button>
              </div>
            </div>
          ) : loadingChapter ? (
            <div className="content-loading">
              <div className="loading-spinner large"></div>
              <p>正在展开书页…</p>
            </div>
          ) : (
            <div
              className="content-scroll"
              ref={contentScrollRef}
              style={{ background }}
              onScroll={(e) => {
                const el = e.currentTarget;
                const ratio = el.scrollHeight > el.clientHeight
                  ? el.scrollTop / (el.scrollHeight - el.clientHeight)
                  : 0;
                setScrollRatio(ratio);
              }}
            >
              <article className="content-page">
                <header className="content-header-block">
                  <div className="content-eyebrow">
                    <span className="eyebrow-line" />
                    <span className="eyebrow-text">第 {chapters[currentIndex]?.chapter_number || currentIndex + 1} 章</span>
                    <span className="eyebrow-line" />
                  </div>
                  <h1 className="content-chapter-title">
                    {chapters[currentIndex]?.title || '无题'}
                  </h1>
                  <div className="content-meta">
                    {displayMode === 'highlight' && (
                      <span className="meta-enriched-badge">高亮 diff 模式</span>
                    )}
                    {displayMode === 'merged' && (
                      <span className="meta-enriched-badge">合并阅读模式</span>
                    )}
                    {displayMode === 'sidebyside' && (
                      <span className="meta-enriched-badge">并排对比模式</span>
                    )}
                    {currentEnrichment?.has_applied && displayMode === 'original' && (
                      <span className="meta-enriched-badge">已应用 AI 加料</span>
                    )}
                    {currentEnrichment?.rewrite_status === 'done' &&
                      !currentEnrichment?.has_applied &&
                      displayMode === 'original' && (
                        <span className="meta-enriched-hint">该章有待应用的加料</span>
                      )}
                    <span>{readMinutes > 0 ? `约 ${readMinutes} 分钟阅读` : '短章'}</span>
                    <span className="meta-dot">·</span>
                    <span>{contentLength.toLocaleString()} 字</span>
                    {contentDirty && (
                      <>
                        <span className="meta-dot">·</span>
                        <span className="meta-dirty">未保存的修改</span>
                      </>
                    )}
                  </div>
                  <div className="content-divider" aria-hidden="true">
                    <span className="divider-ornament">❦</span>
                  </div>
                </header>

                {/* 阅读器内"显示模式"工具条 (仅在有加料时显示) */}
                {currentEnrichment?.rewrite_status === 'done' && currentEnrichment?.rewrite_text && (
                  <div className="content-display-modes">
                    {[
                      { k: 'original', label: '仅原文' },
                      { k: 'merged', label: '合并阅读' },
                      { k: 'sidebyside', label: '并排对比' },
                      { k: 'highlight', label: '高亮 diff' },
                    ].map((m) => (
                      <button
                        key={m.k}
                        type="button"
                        className={`content-display-mode-btn ${
                          displayMode === m.k ? 'active' : ''
                        }`}
                        onClick={async () => {
                          if (m.k === 'highlight' && !previewSegments) {
                            // 第一次切到 highlight 时主动拉 diff
                            try {
                              const data = await api.enrichment.diff(chapter.id);
                              setPreviewSegments(data.segments);
                              setPreviewTruncated(data.truncated);
                            } catch (err) {
                              toast.error(
                                err instanceof ApiError ? err.message : '加载 diff 失败'
                              );
                              return;
                            }
                          }
                          setDisplayMode(m.k);
                        }}
                      >
                        {m.label}
                      </button>
                    ))}
                  </div>
                )}

                {/* 正文区: 4 种模式分支 */}
                {(displayMode === 'original' || displayMode === 'highlight') && (
                  <div
                    className={`content-text ${displayMode === 'highlight' ? 'diff-mode' : ''}`}
                    style={{
                      fontSize: `${fontSize}px`,
                      lineHeight,
                      letterSpacing: `${letterSpacing}px`,
                      color: textColor,
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {contentSegments.map((seg, i) => {
                      if (displayMode === 'highlight' && seg.diffType) {
                        if (seg.diffType === 'added') {
                          // eslint-disable-next-line react/no-array-index-key
                          return <ins key={`d-${i}`} className="reader-diff-added">{seg.text}</ins>;
                        }
                        if (seg.diffType === 'removed') {
                          // eslint-disable-next-line react/no-array-index-key
                          return <del key={`d-${i}`} className="reader-diff-removed">{seg.text}</del>;
                        }
                        // eslint-disable-next-line react/no-array-index-key
                        return <span key={`d-${i}`}>{seg.text}</span>;
                      }
                      if (seg.type === 'plain') {
                        // eslint-disable-next-line react/no-array-index-key
                        return <span key={`p-${i}`}>{seg.text}</span>;
                      }
                      return (
                        <mark
                          // eslint-disable-next-line react/no-array-index-key
                          key={`m-${i}`}
                          ref={setHighlightRef(seg.matchIndex)}
                          data-find-index={seg.matchIndex}
                          className={`find-match${seg.isCurrent ? ' find-match-current' : ''}`}
                        >
                          {seg.text}
                        </mark>
                      );
                    })}
                  </div>
                )}

                {displayMode === 'merged' && (
                  <div className="content-merged-wrap">
                    <MergedReader
                      original={currentContent || ''}
                      rewrite={currentEnrichment?.rewrite_text || ''}
                      diffSegments={previewSegments}
                    />
                  </div>
                )}

                {displayMode === 'sidebyside' && (
                  <div className="content-sidebyside-wrap">
                    <SideBySideReader
                      original={currentContent || ''}
                      rewrite={currentEnrichment?.rewrite_text || ''}
                      diffSegments={previewSegments}
                    />
                  </div>
                )}

                <footer className="content-footer">
                  <div className="content-divider" aria-hidden="true">
                    <span className="divider-ornament">❦</span>
                  </div>
                  <div className="content-end">
                    <span className="end-label">本章节完</span>
                    {currentIndex < chapters.length - 1 ? (
                      <button
                        type="button"
                        className="end-next-btn"
                        onClick={() => setCurrentIndex((i) => Math.min(chapters.length - 1, i + 1))}
                      >
                        继续阅读下一章 →
                      </button>
                    ) : (
                      <span className="end-final">您已抵达全卷之末 ✦</span>
                    )}
                  </div>
                </footer>
              </article>
            </div>
          )}

          <div className="reader-navigation">
            <div className="nav-progress-track" aria-hidden="true">
              <div
                className="nav-progress-fill"
                style={{
                  width: chapters.length > 0
                    ? `${((currentIndex + 1) / chapters.length) * 100}%`
                    : '0%',
                }}
              />
            </div>
            <div className="nav-row">
              <button
                type="button"
                className="nav-btn prev-btn"
                onClick={() => setCurrentIndex((i) => Math.max(0, i - 1))}
                disabled={currentIndex <= 0}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span>上一章</span>
              </button>
              <div className="chapter-progress">
                <span className="progress-current">{chapters.length === 0 ? 0 : currentIndex + 1}</span>
                <span className="progress-sep">/</span>
                <span className="progress-total">{chapters.length}</span>
              </div>
              <button
                type="button"
                className="nav-btn next-btn"
                onClick={() => setCurrentIndex((i) => Math.min(chapters.length - 1, i + 1))}
                disabled={currentIndex >= chapters.length - 1}
              >
                <span>下一章</span>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          </div>
        </div>
        {showEnrichmentPanel && (
          <EnrichmentSidePanel
            novelId={novelId}
            chapter={chapters[currentIndex]}
            novelTitle={novel?.title}
            models={effectiveModels}
            selectedModelId={selectedModelId}
            onModelChange={setSelectedModelId}
            onGoToWorkbench={onGoToWorkbench}
            scrollRef={contentScrollRef}
            onApplied={() => {
              // 重新拉当前章节内容
              if (chapters[currentIndex]) {
                api.novels
                  .chapter(novelId, chapters[currentIndex].id)
                  .then((data) => {
                    setContent(data.content || '');
                    setEnrichmentMap((m) => ({ ...m, [chapters[currentIndex].id]: undefined }));
                  })
                  .catch(() => {});
              }
            }}
            onReverted={() => {
              if (chapters[currentIndex]) {
                api.novels
                  .chapter(novelId, chapters[currentIndex].id)
                  .then((data) => {
                    setContent(data.content || '');
                  })
                  .catch(() => {});
              }
            }}
            onOpenHistory={() => setShowHistoryFor(chapters[currentIndex]?.id)}
          />
        )}
      </div>
      {showHistoryFor && (
        <SuggestionHistoryModal
          chapterId={showHistoryFor}
          onClose={() => setShowHistoryFor(null)}
          onReverted={() => {
            if (showHistoryFor) {
              api.novels
                .chapter(novelId, showHistoryFor)
                .then((data) => {
                  if (
                    chapters[currentIndex] &&
                    chapters[currentIndex].id === showHistoryFor
                  ) {
                    setContent(data.content || '');
                  }
                })
                .catch(() => {});
            }
          }}
        />
      )}
    </div>
  );
}

export default NovelReader;
