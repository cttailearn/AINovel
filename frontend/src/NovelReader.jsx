import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { getBackendUrl } from './config.js';
import './App.css';

const READING_PRESETS = [
  { name: '默认', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#f8f5f0', color: '#333', sidebarBg: '#fff', sidebarColor: '#333' },
  { name: '护眼', fontSize: 18, lineHeight: 2, letterSpacing: 1, background: '#f0e6d3', color: '#5a4a3a', sidebarBg: '#e8dcc8', sidebarColor: '#4a3a2a' },
  { name: '深夜', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#1a1a1a', color: '#b0b0b0', sidebarBg: '#252525', sidebarColor: '#b0b0b0' },
  { name: '纯黑', fontSize: 18, lineHeight: 1.8, letterSpacing: 0, background: '#000', color: '#fff', sidebarBg: '#111', sidebarColor: '#fff' },
  { name: '书籍', fontSize: 16, lineHeight: 2.2, letterSpacing: 0.5, background: '#faf8f5', color: '#2c2c2c', sidebarBg: '#f0ebe3', sidebarColor: '#2c2c2c' },
];

function NovelReader({ novelId, onBack, refetch }) {
  const [novel, setNovel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [currentChapterIndex, setCurrentChapterIndex] = useState(0);
  const [currentContent, setCurrentContent] = useState('');
  const [loadingChapter, setLoadingChapter] = useState(false);
  
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showEditPanel, setShowEditPanel] = useState(false);
  
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
  const [editedContent, setEditedContent] = useState('');
  const [hasChanges, setHasChanges] = useState(false);
  
  const contentRef = useRef(null);
  const contentAreaRef = useRef(null);

  useEffect(() => {
    loadNovel();
  }, [novelId]);

  useEffect(() => {
    if (chapters.length > 0 && currentChapterIndex < chapters.length) {
      loadChapterContent(currentChapterIndex);
    } else if (chapters.length > 0 && currentChapterIndex >= chapters.length) {
      setCurrentChapterIndex(0);
    }
  }, [currentChapterIndex, chapters]);

  useEffect(() => {
    if (novel && chapters.length === 0 && novel.chapters && novel.chapters.length > 0) {
      setChapters(novel.chapters);
    }
  }, [novel]);

  const loadNovel = async () => {
    setLoading(true);
    setError(null);
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/novels/${novelId}`);
      if (!response.ok) throw new Error('获取小说详情失败');
      const data = await response.json();
      setNovel(data);
      setChapters(data.chapters || []);
      if (data.chapters && data.chapters.length > 0) {
        setCurrentChapterIndex(0);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadChapterContent = async (index) => {
    if (index < 0 || index >= chapters.length) return;
    
    const chapter = chapters[index];
    setLoadingChapter(true);
    setCurrentContent('');
    setHasChanges(false);
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/novels/${novelId}/chapters/${chapter.id}`);
      
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '获取章节失败');
      }
      
      const data = await response.json();
      const content = data.content || '';
      setCurrentContent(content);
      setEditedContent(content);
      setFindResults([]);
      setCurrentResultIndex(-1);
    } catch (err) {
      console.error('获取章节内容失败:', err);
      setCurrentContent(`加载失败: ${err.message}`);
    } finally {
      setLoadingChapter(false);
    }
  };

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

  const goToPrevChapter = () => {
    if (currentChapterIndex > 0) {
      setCurrentChapterIndex(prev => prev - 1);
    }
  };

  const goToNextChapter = () => {
    if (currentChapterIndex < chapters.length - 1) {
      setCurrentChapterIndex(prev => prev + 1);
    }
  };

  const handleContentChange = (e) => {
    setEditedContent(e.target.value);
    setHasChanges(true);
  };

  const handleFind = () => {
    if (!findText) return;
    const regex = new RegExp(findText, 'gi');
    const matches = [];
    let match;
    while ((match = regex.exec(editedContent)) !== null) {
      matches.push({
        index: match.index,
        length: match[0].length,
        text: match[0]
      });
    }
    setFindResults(matches);
    setCurrentResultIndex(matches.length > 0 ? 0 : -1);
  };

  const handleReplace = () => {
    if (!findText || currentResultIndex < 0) return;
    const result = findResults[currentResultIndex];
    const newContent = editedContent.substring(0, result.index) + 
                       replaceText + 
                       editedContent.substring(result.index + result.length);
    setEditedContent(newContent);
    setHasChanges(true);
    handleFind();
  };

  const handleReplaceAll = () => {
    if (!findText) return;
    const newContent = editedContent.replace(new RegExp(findText, 'g'), replaceText);
    setEditedContent(newContent);
    setHasChanges(true);
    setFindResults([]);
    setCurrentResultIndex(-1);
  };

  const scrollToResult = (index) => {
    setCurrentResultIndex(index);
    if (contentAreaRef.current) {
      const textarea = contentAreaRef.current.querySelector('textarea');
      if (textarea) {
        textarea.focus();
        const pos = findResults[index].index;
        textarea.setSelectionRange(pos, pos + findResults[index].length);
      }
    }
  };

  const styles = useMemo(() => ({
    '--reader-bg': background,
    '--reader-color': textColor,
    '--reader-font-size': `${fontSize}px`,
    '--reader-line-height': lineHeight,
    '--reader-letter-spacing': `${letterSpacing}px`,
    '--sidebar-bg': sidebarBg,
    '--sidebar-color': sidebarColor,
  }), [background, textColor, fontSize, lineHeight, letterSpacing, sidebarBg, sidebarColor]);

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
        <button onClick={onBack}>返回列表</button>
      </div>
    );
  }

  return (
    <div className="novel-reader" style={styles}>
      <div className="reader-toolbar">
        <button className="toolbar-btn back-btn" onClick={onBack} title="返回">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="2"/>
          </svg>
        </button>
        <span className="reader-title">{novel.title}</span>
        <div className="toolbar-actions">
          <button 
            className={`toolbar-btn ${showEditPanel ? 'active' : ''}`}
            onClick={() => setShowEditPanel(!showEditPanel)}
            title="编辑"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="2"/>
              <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="2"/>
            </svg>
          </button>
          <button 
            className={`toolbar-btn ${showSettings ? 'active' : ''}`}
            onClick={() => setShowSettings(!showSettings)}
            title="设置"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2"/>
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" stroke="currentColor" strokeWidth="2"/>
            </svg>
          </button>
        </div>
      </div>

      {showSettings && (
        <div className="reader-settings-panel">
          <div className="settings-header">
            <h3>阅读设置</h3>
            <button onClick={() => setShowSettings(false)}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2"/>
              </svg>
            </button>
          </div>
          
          <div className="settings-section">
            <label>预设主题</label>
            <div className="preset-buttons">
              {READING_PRESETS.map((preset, index) => (
                <button
                  key={index}
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
            <input
              type="range"
              min="12"
              max="28"
              value={fontSize}
              onChange={(e) => setFontSize(Number(e.target.value))}
            />
          </div>

          <div className="settings-section">
            <label>行间距: {lineHeight}</label>
            <input
              type="range"
              min="1.2"
              max="3"
              step="0.1"
              value={lineHeight}
              onChange={(e) => setLineHeight(Number(e.target.value))}
            />
          </div>

          <div className="settings-section">
            <label>字符间距: {letterSpacing}px</label>
            <input
              type="range"
              min="0"
              max="5"
              step="0.5"
              value={letterSpacing}
              onChange={(e) => setLetterSpacing(Number(e.target.value))}
            />
          </div>

          <div className="settings-section colors-section">
            <div className="color-option">
              <label>背景色</label>
              <div className="color-options">
                <button className="color-btn" style={{background: '#f8f5f0'}} onClick={() => setBackground('#f8f5f0')} />
                <button className="color-btn" style={{background: '#f0e6d3'}} onClick={() => setBackground('#f0e6d3')} />
                <button className="color-btn" style={{background: '#e8f4e8'}} onClick={() => setBackground('#e8f4e8')} />
                <button className="color-btn" style={{background: '#1a1a1a'}} onClick={() => setBackground('#1a1a1a')} />
                <button className="color-btn" style={{background: '#000'}} onClick={() => setBackground('#000')} />
              </div>
            </div>
            <div className="color-option">
              <label>文字色</label>
              <div className="color-options">
                <button className="color-btn" style={{background: '#333', border: '2px solid #fff'}} onClick={() => setTextColor('#333')} />
                <button className="color-btn" style={{background: '#5a4a3a', border: '2px solid #fff'}} onClick={() => setTextColor('#5a4a3a')} />
                <button className="color-btn" style={{background: '#2c5f2c', border: '2px solid #fff'}} onClick={() => setTextColor('#2c5f2c')} />
                <button className="color-btn" style={{background: '#b0b0b0', border: '2px solid #333'}} onClick={() => setTextColor('#b0b0b0')} />
                <button className="color-btn" style={{background: '#fff', border: '2px solid #333'}} onClick={() => setTextColor('#fff')} />
              </div>
            </div>
          </div>
        </div>
      )}

      {showEditPanel && (
        <div className="reader-edit-panel">
          <div className="edit-header">
            <h3>查找替换</h3>
            <button onClick={() => setShowEditPanel(false)}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2"/>
              </svg>
            </button>
          </div>
          
          <div className="find-replace-form">
            <div className="form-row">
              <input
                type="text"
                placeholder="查找内容"
                value={findText}
                onChange={(e) => setFindText(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleFind()}
              />
              <button className="find-btn" onClick={handleFind}>查找</button>
            </div>
            <div className="form-row">
              <input
                type="text"
                placeholder="替换为"
                value={replaceText}
                onChange={(e) => setReplaceText(e.target.value)}
              />
              <button className="replace-btn" onClick={handleReplace}>替换</button>
              <button className="replace-all-btn" onClick={handleReplaceAll}>全部替换</button>
            </div>
            {findResults.length > 0 && (
              <div className="find-results-info">
                找到 {findResults.length} 个匹配
                <div className="result-nav">
                  <button disabled={currentResultIndex <= 0} onClick={() => scrollToResult(currentResultIndex - 1)}>上一个</button>
                  <span>{currentResultIndex + 1} / {findResults.length}</span>
                  <button disabled={currentResultIndex >= findResults.length - 1} onClick={() => scrollToResult(currentResultIndex + 1)}>下一个</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="reader-main">
        <div className={`reader-sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
          <div className="sidebar-header">
            <h3>目录</h3>
            <button className="collapse-btn" onClick={() => setSidebarCollapsed(!sidebarCollapsed)}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                {sidebarCollapsed ? (
                  <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2"/>
                ) : (
                  <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2"/>
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
                    className={`chapter-item ${currentChapterIndex === index ? 'active' : ''}`}
                    onClick={() => setCurrentChapterIndex(index)}
                  >
                    <span className="chapter-num">{chapter.chapter_number}</span>
                    <span className="chapter-title">{chapter.title}</span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        <div className="reader-content" ref={contentAreaRef}>
          {loadingChapter ? (
            <div className="content-loading">
              <div className="loading-spinner large"></div>
              <p>加载中...</p>
            </div>
          ) : (
            <div className="content-wrapper">
              {showEditPanel ? (
                <textarea
                  ref={contentRef}
                  className="content-textarea"
                  value={editedContent}
                  onChange={handleContentChange}
                  style={{
                    fontSize: `${fontSize}px`,
                    lineHeight: lineHeight,
                    letterSpacing: `${letterSpacing}px`,
                    color: textColor,
                    background: background
                  }}
                />
              ) : (
                <div 
                  className="content-text"
                  style={{
                    fontSize: `${fontSize}px`,
                    lineHeight: lineHeight,
                    letterSpacing: `${letterSpacing}px`,
                    color: textColor,
                    background: background
                  }}
                >
                  {currentContent || '暂无内容'}
                </div>
              )}
            </div>
          )}

          <div className="reader-navigation">
            <button 
              className="nav-btn prev-btn"
              onClick={goToPrevChapter}
              disabled={currentChapterIndex <= 0}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2"/>
              </svg>
              上一章
            </button>
            
            <div className="chapter-progress">
              <span>{currentChapterIndex + 1} / {chapters.length}</span>
            </div>
            
            <button 
              className="nav-btn next-btn"
              onClick={goToNextChapter}
              disabled={currentChapterIndex >= chapters.length - 1}
            >
              下一章
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default NovelReader;