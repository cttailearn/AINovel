import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { tryCompileRegex } from '../utils/regex.js';
import { useToast } from './Toast/ToastProvider.jsx';
import '../App.css';

const READING_PRESETS = [
  { name: '默认', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#f8f5f0', color: '#333', sidebarBg: '#fff', sidebarColor: '#333' },
  { name: '护眼', fontSize: 18, lineHeight: 2, letterSpacing: 1, background: '#f0e6d3', color: '#5a4a3a', sidebarBg: '#e8dcc8', sidebarColor: '#4a3a2a' },
  { name: '深夜', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#1a1a1a', color: '#b0b0b0', sidebarBg: '#252525', sidebarColor: '#b0b0b0' },
  { name: '纯黑', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#000', color: '#fff', sidebarBg: '#111', sidebarColor: '#fff' },
  { name: '书籍', fontSize: 16, lineHeight: 2.2, letterSpacing: 0.5, background: '#faf8f5', color: '#2c2c2c', sidebarBg: '#f0ebe3', sidebarColor: '#2c2c2c' },
];

function NovelReader({ novelId, onBack }) {
  const toast = useToast();
  const [novel, setNovel] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingChapter, setLoadingChapter] = useState(false);
  const [error, setError] = useState(null);

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

  const abortRef = useRef(null);
  const textareaRef = useRef(null);

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
      } catch (err) {
        if (err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : '加载失败');
      } finally {
        setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [novelId]);

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

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowLeft') setCurrentIndex((i) => Math.max(0, i - 1));
      if (e.key === 'ArrowRight') setCurrentIndex((i) => Math.min(chapters.length - 1, i + 1));
      if (e.key === 'Escape') onBack?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [chapters.length, onBack]);

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
    while ((m = re.exec(content)) !== null) {
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
    handleFind();
  };

  const handleReplaceAll = () => {
    if (!findText) return;
    try {
      const re = new RegExp(findText, 'g');
      const next = content.replace(re, replaceText);
      setContent(next);
      setFindResults([]);
      setCurrentResultIndex(-1);
      toast.success('已替换');
    } catch (err) {
      toast.error(`无效正则: ${err.message}`);
    }
  };

  const scrollToResult = (index) => {
    setCurrentResultIndex(index);
    if (!textareaRef.current) return;
    const result = findResults[index];
    textareaRef.current.focus();
    textareaRef.current.setSelectionRange(result.index, result.index + result.length);
  };

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
            <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        <span className="reader-title">{novel.title}</span>
        <div className="toolbar-actions">
          <button
            className={`toolbar-btn ${showFindPanel ? 'active' : ''}`}
            type="button"
            onClick={() => setShowFindPanel(!showFindPanel)}
            title="查找替换"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
              <path d="M21 21l-4-4" stroke="currentColor" strokeWidth="2" />
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
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" stroke="currentColor" strokeWidth="2" />
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
              onKeyDown={(e) => e.key === 'Enter' && handleFind()}
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
          {loadingChapter ? (
            <div className="content-loading">
              <div className="loading-spinner large"></div>
              <p>加载中...</p>
            </div>
          ) : (
            <div
              className="content-text"
              style={{
                fontSize: `${fontSize}px`,
                lineHeight,
                letterSpacing: `${letterSpacing}px`,
                color: textColor,
                background,
                whiteSpace: 'pre-wrap',
              }}
            >
              <textarea
                ref={textareaRef}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                spellCheck={false}
                style={{
                  width: '100%',
                  minHeight: '60vh',
                  border: 'none',
                  background: 'transparent',
                  color: 'inherit',
                  fontSize: 'inherit',
                  lineHeight: 'inherit',
                  letterSpacing: 'inherit',
                  resize: 'vertical',
                  outline: 'none',
                  fontFamily: 'inherit',
                }}
              />
            </div>
          )}

          <div className="reader-navigation">
            <button
              type="button"
              className="nav-btn prev-btn"
              onClick={() => setCurrentIndex((i) => Math.max(0, i - 1))}
              disabled={currentIndex <= 0}
            >
              ← 上一章
            </button>
            <div className="chapter-progress">
              <span>
                {chapters.length === 0 ? 0 : currentIndex + 1} / {chapters.length}
              </span>
            </div>
            <button
              type="button"
              className="nav-btn next-btn"
              onClick={() => setCurrentIndex((i) => Math.min(chapters.length - 1, i + 1))}
              disabled={currentIndex >= chapters.length - 1}
            >
              下一章 →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default NovelReader;
