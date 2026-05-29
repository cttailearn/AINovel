import { useState, useEffect, useCallback, useRef } from 'react';
import { getBackendUrl, useApiRequest } from './config.js';
import { useTheme } from './ThemeContext.jsx';
import NovelReader from './NovelReader.jsx';
import './App.css';

const PROVIDER_OPTIONS = [
  { value: 'anthropic', label: 'Anthropic', icon: '🤖', description: 'Claude API' },
  { value: 'openai', label: 'OpenAI', icon: '🔮', description: 'ChatGPT API' },
  { value: 'custom', label: 'Custom', icon: '⚙️', description: 'Custom API' }
];

const PRESET_RULES = [
  { label: '通用', value: '第.{1,30}章' },
  { label: '数字', value: '第\\d+章' },
  { label: '中文数字', value: '第[一二三四五六七八九十百千零\\d]+章' },
  { label: '第X章 标题', value: '第.{1,30}章\\s+[^\\n]+' },
];

function ConfigList({ configs, selectedId, onSelect, onToggle, onDelete }) {
  return (
    <div className="config-list">
      <div className="config-list-header">
        <h3>模型列表</h3>
        <span className="config-count">{configs.length}</span>
      </div>
      <div className="config-list-items">
        {configs.length === 0 ? (
          <div className="empty-list">
            <p>暂无模型配置</p>
            <span>点击下方添加新模型开始配置</span>
          </div>
        ) : (
          configs.map(config => (
            <div
              key={config.id}
              className={`config-list-item ${selectedId === config.id ? 'selected' : ''} ${config.enabled ? 'enabled' : 'disabled'}`}
              onClick={() => onSelect(config.id)}
            >
              <div className="config-item-main">
                <span className="config-item-icon">
                  {PROVIDER_OPTIONS.find(p => p.value === config.provider)?.icon || '⚙️'}
                </span>
                <div className="config-item-info">
                  <span className="config-item-name">{config.name || config.provider}</span>
                  <span className="config-item-model">{config.model_name}</span>
                </div>
              </div>
              <div className="config-item-actions">
                <button
                  className={`toggle-btn ${config.enabled ? 'active' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggle(config.id, config.enabled ? 0 : 1);
                  }}
                  title={config.enabled ? '禁用' : '启用'}
                >
                  <span className="toggle-indicator"></span>
                </button>
                <button
                  className="delete-btn-small"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm(`确定删除 "${config.name || config.provider}" 吗？`)) {
                      onDelete(config.id);
                    }
                  }}
                  title="删除"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" stroke="currentColor" strokeWidth="2"/>
                  </svg>
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ConfigEditor({ config, onSave, onTest }) {
  const [formData, setFormData] = useState({
    name: '',
    provider: '',
    model_url: '',
    api_key: '',
    model_name: '',
    enabled: 1
  });
  const [testStatus, setTestStatus] = useState(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config) {
      setFormData({
        id: config.id,
        name: config.name || '',
        provider: config.provider || '',
        model_url: config.model_url || '',
        api_key: config.api_key || '',
        model_name: config.model_name || '',
        enabled: config.enabled ?? 1
      });
    } else {
      setFormData({
        name: '',
        provider: '',
        model_url: '',
        api_key: '',
        model_name: '',
        enabled: 1
      });
    }
    setTestStatus(null);
  }, [config]);

  const providerInfo = PROVIDER_OPTIONS.find(p => p.value === formData.provider) || PROVIDER_OPTIONS[2];

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
    setTestStatus(null);
  };

  const handleProviderSelect = (value) => {
    setFormData(prev => ({
      ...prev,
      provider: value
    }));
  };

  const handleTest = async () => {
    if (!formData.model_url || !formData.api_key || !formData.model_name || !formData.provider) {
      setTestStatus({ success: false, message: '请填写所有必填项' });
      return;
    }
    
    setTesting(true);
    setTestStatus(null);
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/models/test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          provider: formData.provider,
          model_url: formData.model_url,
          api_key: formData.api_key,
          model_name: formData.model_name
        }),
      });
      const result = await response.json();
      setTestStatus(result);
    } catch (err) {
      setTestStatus({ success: false, message: err.message });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (!formData.name || !formData.provider || !formData.model_url || !formData.api_key || !formData.model_name) {
      return;
    }
    
    setSaving(true);
    await onSave(formData, () => setSaving(false));
  };

  const isValid = formData.name && formData.provider && formData.model_url && formData.api_key && formData.model_name;

  return (
    <div className={`config-editor ${testStatus ? (testStatus.success ? 'success-card' : 'error-card') : ''}`}>
      <div className="editor-header">
        <div className="editor-title">
          <span className="provider-icon">{providerInfo.icon}</span>
          <div className="editor-title-text">
            <h2>{config ? (formData.name || '编辑模型') : '新建模型'}</h2>
            <span className="editor-provider">{providerInfo.description}</span>
          </div>
        </div>
        {config && (
          <div className={`enabled-badge ${formData.enabled ? 'enabled' : 'disabled'}`}>
            <span className={`status-dot ${formData.enabled ? 'success' : 'error-dot'}`}></span>
            <span>{formData.enabled ? '已启用' : '已禁用'}</span>
          </div>
        )}
      </div>
      
      <div className="form-group">
        <label>配置名称 *</label>
        <input
          type="text"
          name="name"
          value={formData.name}
          onChange={handleChange}
          placeholder="我的 Claude API"
        />
      </div>

      <div className="form-group">
        <label>提供商 *</label>
        <div className="provider-selector">
          {PROVIDER_OPTIONS.map(opt => (
            <button
              key={opt.value}
              type="button"
              className={`provider-option ${formData.provider === opt.value ? 'selected' : ''}`}
              onClick={() => handleProviderSelect(opt.value)}
            >
              <span className="provider-option-icon">{opt.icon}</span>
              <span className="provider-option-label">{opt.label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="form-group">
        <label>模型 URL *</label>
        <input
          type="text"
          name="model_url"
          value={formData.model_url}
          onChange={handleChange}
          placeholder="https://api.example.com/v1"
        />
      </div>

      <div className="form-group">
        <label>API 密钥 *</label>
        <input
          type="password"
          name="api_key"
          value={formData.api_key}
          onChange={handleChange}
          placeholder="sk-..."
        />
      </div>

      <div className="form-group">
        <label>模型名称 *</label>
        <input
          type="text"
          name="model_name"
          value={formData.model_name}
          onChange={handleChange}
          placeholder="gpt-4, claude-3-5-sonnet, 等"
        />
      </div>

      <div className="form-group toggle-group">
        <label>启用</label>
        <label className="switch">
          <input
            type="checkbox"
            checked={formData.enabled === 1}
            onChange={(e) => setFormData(prev => ({ ...prev, enabled: e.target.checked ? 1 : 0 }))}
          />
          <span className="slider"></span>
        </label>
      </div>

      <div className="button-group">
        <button 
          className={`test-button ${testing ? 'testing' : ''}`} 
          onClick={handleTest}
          disabled={testing || !isValid}
        >
          {testing ? (
            <span className="loading-spinner"></span>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2"/>
              <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
          测试连接
        </button>
        
        <button 
          className={`save-button ${saving ? 'saving' : ''}`} 
          onClick={handleSave}
          disabled={saving || !isValid}
        >
          {saving ? (
            <span className="loading-spinner"></span>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z" stroke="currentColor" strokeWidth="2"/>
              <path d="M17 21v-8H7v8M7 3v5h8" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
          {config ? '更新' : '保存'}
        </button>
      </div>

      {testStatus && (
        <div className={`status-message ${testStatus.success ? 'success-message' : 'error-message'}`}>
          {testStatus.success ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2"/>
              <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2"/>
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2"/>
              <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
          <span>{testStatus.message}</span>
          {testStatus.response_time && (
            <span className="response-time">{testStatus.response_time}秒</span>
          )}
        </div>
      )}
    </div>
  );
}

function NovelList({ novels, onSelect, onDelete, refetch, onStartReading }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [deletingId, setDeletingId] = useState(null);
  const fileInputRef = useRef(null);

  const filteredNovels = novels.filter(novel => 
    novel.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    novel.author.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    if (!file.name.endsWith('.txt')) {
      alert('只支持 TXT 格式文件');
      return;
    }

    try {
      const API_BASE = getBackendUrl();
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${API_BASE}/api/novels/upload`, {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '上传失败');
      }

      const result = await response.json();
      await refetch();
      onSelect(result.id);
    } catch (err) {
      alert(err.message || '上传失败');
    }
    
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (id) => {
    setDeletingId(id);
    try {
      const API_BASE = getBackendUrl();
      await fetch(`${API_BASE}/api/novels/${id}`, { method: 'DELETE' });
      await refetch();
    } catch (err) {
      console.error('删除失败:', err);
    } finally {
      setDeletingId(null);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'parsed':
        return <span className="status-badge status-parsed">已解析</span>;
      case 'pending':
        return <span className="status-badge status-pending">待解析</span>;
      default:
        return <span className="status-badge">{status}</span>;
    }
  };

  return (
    <div className="novel-list-view">
      <input
        type="file"
        ref={fileInputRef}
        accept=".txt"
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />
      <div className="list-header">
        <div className="search-box">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2"/>
            <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2"/>
          </svg>
          <input
            type="text"
            placeholder="搜索小说..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <button className="upload-btn" onClick={handleUploadClick}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2"/>
          </svg>
          上传小说
        </button>
      </div>

      <div className="novel-cards">
        {filteredNovels.length === 0 ? (
          <div className="empty-novels">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none">
              <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="2"/>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="2"/>
            </svg>
            <p>暂无小说</p>
            <span>点击上方按钮上传第一本小说</span>
          </div>
        ) : (
          filteredNovels.map(novel => (
            <div key={novel.id} className={`novel-card ${novel.chapter_count > 0 ? 'has-chapters' : ''}`}>
              <div className="novel-card-header">
                <div className="novel-icon-wrapper" onClick={() => onSelect(novel.id)}>
                  <div className="novel-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                      <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="2"/>
                      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="2"/>
                    </svg>
                  </div>
                  {getStatusBadge(novel.status)}
                </div>
                <div className="novel-card-actions">
                  {novel.chapter_count > 0 && (
                    <button
                      className="card-read-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        onStartReading(novel.id);
                      }}
                      title="立即阅读"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" stroke="currentColor" strokeWidth="2"/>
                        <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" stroke="currentColor" strokeWidth="2"/>
                      </svg>
                    </button>
                  )}
                  <button
                    className="card-delete-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm(`确定删除《${novel.title}》吗？`)) {
                        handleDelete(novel.id);
                      }
                    }}
                    disabled={deletingId === novel.id}
                  >
                    {deletingId === novel.id ? (
                      <span className="loading-spinner small"></span>
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" stroke="currentColor" strokeWidth="2"/>
                      </svg>
                    )}
                  </button>
                </div>
              </div>
              
              <div className="novel-card-body" onClick={() => onSelect(novel.id)}>
                <h3 className="novel-title">{novel.title}</h3>
                <p className="novel-author">作者：{novel.author}</p>
                
                <div className="novel-meta">
                  <span className="chapter-count">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <path d="M9 12h6M9 16h6M17 21H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" stroke="currentColor" strokeWidth="2"/>
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

function NovelDetail({ novelId, onBack, refetch, onStartReading }) {
  const [novel, setNovel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [parseRule, setParseRule] = useState('');
  const [parsing, setParsing] = useState(false);
  const [parseResult, setParseResult] = useState(null);
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [chapterContent, setChapterContent] = useState(null);
  const [loadingChapter, setLoadingChapter] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editAuthor, setEditAuthor] = useState('');
  const [rawReadingMode, setRawReadingMode] = useState(false);
  const [rawChapters, setRawChapters] = useState([]);
  const [loadingRaw, setLoadingRaw] = useState(false);
  const [chunkSize, setChunkSize] = useState(5000);
  const [parsingFixed, setParsingFixed] = useState(false);

  useEffect(() => {
    loadNovel();
  }, [novelId]);

  useEffect(() => {
    setSelectedChapter(null);
    setChapterContent(null);
    setRawReadingMode(false);
    setRawChapters([]);
  }, [novelId]);

  const loadNovel = async () => {
    setLoading(true);
    setError(null);
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/novels/${novelId}`);
      if (!response.ok) throw new Error('获取小说详情失败');
      const data = await response.json();
      setNovel(data);
      setParseRule(data.parse_rule || PRESET_RULES[0].value);
      setEditTitle(data.title);
      setEditAuthor(data.author);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveEdit = async () => {
    try {
      const API_BASE = getBackendUrl();
      const formData = new FormData();
      formData.append('title', editTitle);
      formData.append('author', editAuthor);
      
      await fetch(`${API_BASE}/api/novels/${novelId}`, {
        method: 'PUT',
        body: formData
      });
      
      setEditing(false);
      await loadNovel();
      await refetch();
    } catch (err) {
      console.error('保存失败:', err);
    }
  };

  const handleParse = async () => {
    if (!parseRule.trim()) {
      setParseResult({ success: false, message: '请输入解析规则' });
      return;
    }
    
    setParsing(true);
    setParseResult(null);
    try {
      const API_BASE = getBackendUrl();
      const formData = new FormData();
      formData.append('rule', parseRule);
      
      const response = await fetch(`${API_BASE}/api/novels/${novelId}/parse`, {
        method: 'POST',
        body: formData
      });
      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.detail || result.message || '解析失败');
      }
      
      setParseResult(result);
      if (result.success) {
        await loadNovel();
        await refetch();
      } else {
        alert(result.message || '解析失败：未找到匹配的章节');
      }
    } catch (err) {
      setParseResult({ success: false, message: err.message });
      alert(err.message || '解析失败');
    } finally {
      setParsing(false);
    }
  };

  const handleLoadRawContent = async () => {
    setLoadingRaw(true);
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/novels/${novelId}/raw?chunk_size=${chunkSize}`);
      const data = await response.json();
      setRawChapters(data.chunks || []);
      setRawReadingMode(true);
    } catch (err) {
      console.error('加载原始内容失败:', err);
      alert('加载失败');
    } finally {
      setLoadingRaw(false);
    }
  };

  const handleParseFixed = async () => {
    setParsingFixed(true);
    setParseResult(null);
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/novels/${novelId}/parse-fixed?chunk_size=${chunkSize}`, {
        method: 'POST'
      });
      
      const contentType = response.headers.get('content-type');
      let result;
      
      if (contentType && contentType.includes('application/json')) {
        result = await response.json();
      } else {
        const text = await response.text();
        console.error('Parse-fixed response not JSON:', text.substring(0, 500));
        throw new Error('服务器返回了非 JSON 格式的响应');
      }
      
      if (!response.ok) {
        throw new Error(result.detail || result.message || '解析失败');
      }
      
      setParseResult(result);
      if (result.success) {
        await loadNovel();
        await refetch();
      } else {
        alert(result.message || '解析失败');
      }
    } catch (err) {
      console.error('固定字数解析失败:', err);
      setParseResult({ success: false, message: err.message });
      alert(err.message || '解析失败');
    } finally {
      setParsingFixed(false);
    }
  };

  const handleChapterClick = async (chapter) => {
    setSelectedChapter(chapter);
    setLoadingChapter(true);
    setChapterContent(null);
    try {
      const API_BASE = getBackendUrl();
      const response = await fetch(`${API_BASE}/api/novels/${novelId}/chapters/${chapter.id}`);
      const data = await response.json();
      setChapterContent(data);
    } catch (err) {
      console.error('获取章节内容失败:', err);
    } finally {
      setLoadingChapter(false);
    }
  };

  if (loading) {
    return (
      <div className="novel-detail loading">
        <div className="loading-spinner large"></div>
        <p>加载中...</p>
      </div>
    );
  }

  if (error || !novel) {
    return (
      <div className="novel-detail error">
        <p>{error || '小说不存在'}</p>
        <button onClick={onBack}>返回列表</button>
      </div>
    );
  }

  return (
    <div className="novel-detail">
      <div className="detail-header">
        <button className="back-btn" onClick={onBack}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="2"/>
          </svg>
        </button>
        {editing ? (
          <div className="edit-form">
            <input
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              placeholder="小说标题"
            />
            <input
              type="text"
              value={editAuthor}
              onChange={(e) => setEditAuthor(e.target.value)}
              placeholder="作者"
            />
            <button className="save-edit-btn" onClick={handleSaveEdit}>保存</button>
            <button className="cancel-edit-btn" onClick={() => setEditing(false)}>取消</button>
          </div>
        ) : (
          <div className="detail-title">
            <h2>{novel.title}</h2>
            <p>作者：{novel.author}</p>
          </div>
        )}
        <button className="edit-btn" onClick={() => setEditing(true)} title="编辑">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="2"/>
            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="2"/>
          </svg>
        </button>
      </div>

      {novel.status !== 'parsed' && (
        <div className="raw-reading-section">
          <h3>直接阅读</h3>
          <p className="raw-hint">小说尚未解析，可以直接阅读原文内容</p>
          <div className="chunk-size-selector">
            <label>每章字数：</label>
            <select value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))}>
              <option value={3000}>3000字</option>
              <option value={5000}>5000字</option>
              <option value={8000}>8000字</option>
              <option value={10000}>10000字</option>
            </select>
          </div>
          <button
            className={`raw-read-btn ${loadingRaw ? 'loading' : ''}`}
            onClick={handleLoadRawContent}
            disabled={loadingRaw}
          >
            {loadingRaw ? (
              <span className="loading-spinner"></span>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" stroke="currentColor" strokeWidth="2"/>
                <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" stroke="currentColor" strokeWidth="2"/>
              </svg>
            )}
            加载原文
          </button>
        </div>
      )}

      <div className="parse-section">
        <div className="parse-section-header">
          <h3>
            章节解析
            {novel.chapters && novel.chapters.length > 0 && (
              <span className="chapter-count">{novel.chapters.length} 章</span>
            )}
          </h3>
          {novel.chapters && novel.chapters.length > 0 && (
            <button className="start-reading-btn" onClick={() => onStartReading(novelId)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" stroke="currentColor" strokeWidth="2"/>
                <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" stroke="currentColor" strokeWidth="2"/>
              </svg>
              开始阅读
            </button>
          )}
        </div>
        
        <div className="preset-rules">
          <span className="preset-label">预设规则：</span>
          {PRESET_RULES.map((rule, index) => (
            <button
              key={index}
              className={`preset-btn ${parseRule === rule.value ? 'active' : ''}`}
              onClick={() => setParseRule(rule.value)}
              title={rule.value}
            >
              {rule.label}
            </button>
          ))}
        </div>

        <div className="rule-input-group">
          <input
            type="text"
            value={parseRule}
            onChange={(e) => setParseRule(e.target.value)}
            placeholder="输入正则表达式"
          />
          <button
            className={`parse-btn ${parsing ? 'parsing' : ''}`}
            onClick={handleParse}
            disabled={parsing}
          >
            {parsing ? (
              <span className="loading-spinner"></span>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" stroke="currentColor" strokeWidth="2"/>
              </svg>
            )}
            解析
          </button>
          <button
            className={`parse-btn parse-fixed-btn ${parsingFixed ? 'parsing' : ''}`}
            onClick={handleParseFixed}
            disabled={parsingFixed}
          >
            {parsingFixed ? (
              <span className="loading-spinner"></span>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="2"/>
              </svg>
            )}
            固定字数解析
          </button>
        </div>

        {parseResult && (
          <div className={`parse-result ${parseResult.success ? 'success' : 'error'}`}>
            {parseResult.success ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2"/>
                <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2"/>
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2"/>
                <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="2"/>
              </svg>
            )}
            <span>{parseResult.message}</span>
          </div>
        )}
      </div>

      <div className="chapters-section">
        <h3>
          {rawReadingMode ? '原始内容' : '章节列表'}
          {rawReadingMode ? (
            <span className="chapter-count">{rawChapters.length} 段</span>
          ) : (
            novel.chapters && <span className="chapter-count">{novel.chapters.length} 章</span>
          )}
          {rawReadingMode && (
            <button className="exit-raw-mode-btn" onClick={() => { setRawReadingMode(false); setRawChapters([]); }}>
              退出原始阅读
            </button>
          )}
        </h3>
        
        {rawReadingMode ? (
          rawChapters.length > 0 ? (
            <div className="chapters-grid">
              {rawChapters.map((chunk, index) => (
                <button
                  key={index}
                  className={`chapter-item ${selectedChapter?.chunk_number === chunk.chunk_number ? 'selected' : ''}`}
                  onClick={() => {
                    setSelectedChapter({
                      chunk_number: chunk.chunk_number,
                      title: chunk.title,
                      content: chunk.content
                    });
                    setChapterContent({ content: chunk.content });
                  }}
                >
                  <span className="chapter-number">{chunk.chunk_number}</span>
                  <span className="chapter-title">{chunk.title}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="no-chapters">
              <p>暂无内容</p>
            </div>
          )
        ) : novel.chapters && novel.chapters.length > 0 ? (
          <div className="chapters-grid">
            {novel.chapters.map(chapter => (
              <button
                key={chapter.id}
                className={`chapter-item ${selectedChapter?.id === chapter.id ? 'selected' : ''}`}
                onClick={() => handleChapterClick(chapter)}
              >
                <span className="chapter-number">{chapter.chapter_number}</span>
                <span className="chapter-title">{chapter.title}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="no-chapters">
            <p>暂无章节，请先设置解析规则并解析，或使用直接阅读功能</p>
          </div>
        )}
      </div>

      {selectedChapter && (
        <div className="chapter-content-panel">
          <div className="content-header">
            <h3>{selectedChapter.title}</h3>
            <button className="close-btn" onClick={() => { setSelectedChapter(null); setChapterContent(null); }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2"/>
              </svg>
            </button>
          </div>
          
          {loadingChapter ? (
            <div className="content-loading">
              <span className="loading-spinner"></span>
              <p>加载中...</p>
            </div>
          ) : chapterContent ? (
            <div className="content-body">
              <p>{chapterContent.content || '暂无内容'}</p>
            </div>
          ) : (
            <div className="content-loading">
              <p>加载失败</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function App() {
  const { theme, toggleTheme } = useTheme();
  const { data: healthData, loading: healthLoading, error: healthError, refetch: refetchHealth } = useApiRequest('/health');
  const { data: configsData, refetch: refetchConfigs } = useApiRequest('/models');
  const { data: novelsData, refetch: refetchNovels } = useApiRequest('/novels');

  const [activeTab, setActiveTab] = useState('models');
  const [selectedConfigId, setSelectedConfigId] = useState(null);
  const [viewMode, setViewMode] = useState('list');
  const [selectedNovelId, setSelectedNovelId] = useState(null);
  const [readingNovelId, setReadingNovelId] = useState(null);

  const configs = configsData?.configs || [];
  const novels = novelsData?.novels || [];
  const selectedConfig = configs.find(c => c.id === selectedConfigId);

  useEffect(() => {
    if (configs.length > 0 && !selectedConfigId) {
      setSelectedConfigId(configs[0].id);
    }
  }, [configs]);

  const handleSave = async (formData, setSaving) => {
    try {
      const API_BASE = getBackendUrl();
      const method = formData.id ? 'PUT' : 'POST';
      const url = formData.id 
        ? `${API_BASE}/api/models/${formData.id}` 
        : `${API_BASE}/api/models`;
      
      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });
      
      if (response.ok) {
        await refetchConfigs();
      }
    } catch (err) {
      console.error('保存错误:', err);
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (id, enabled) => {
    try {
      const API_BASE = getBackendUrl();
      await fetch(`${API_BASE}/api/models/${id}/toggle?enabled=${enabled}`, {
        method: 'PATCH',
      });
      await refetchConfigs();
    } catch (err) {
      console.error('切换错误:', err);
    }
  };

  const handleDelete = async (id) => {
    try {
      const API_BASE = getBackendUrl();
      await fetch(`${API_BASE}/api/models/${id}`, {
        method: 'DELETE',
      });
      if (selectedConfigId === id) {
        setSelectedConfigId(null);
      }
      await refetchConfigs();
    } catch (err) {
      console.error('删除错误:', err);
    }
  };

  const handleNewConfig = () => {
    setSelectedConfigId(null);
  };

  const handleNovelSelect = (id) => {
    setSelectedNovelId(id);
    setViewMode('detail');
  };

  const handleNovelBack = () => {
    setSelectedNovelId(null);
    setViewMode('list');
    refetchNovels();
  };

  const handleStartReading = (id) => {
    setReadingNovelId(id);
  };

  const handleExitReading = () => {
    setReadingNovelId(null);
  };

  return (
    <div className="app-container">
      {readingNovelId && (
        <NovelReader
          novelId={readingNovelId}
          onBack={handleExitReading}
          refetch={refetchNovels}
        />
      )}
      
      <div className="header-actions">
        <button className="theme-toggle" onClick={toggleTheme} title={theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'}>
          {theme === 'dark' ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="5" stroke="currentColor" strokeWidth="2"/>
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" stroke="currentColor" strokeWidth="2"/>
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
        </button>
        <button 
          className={`status-icon ${healthLoading ? 'loading' : healthError ? 'error' : 'success'}`}
          onClick={() => { refetchHealth(); refetchConfigs(); refetchNovels(); }}
          title={healthLoading ? '检查中...' : healthError ? '后端已断开' : '后端已连接'}
        >
          {healthError ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2"/>
              <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="2"/>
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="2"/>
              <path d="M22 4L12 14.01l-3-3" stroke="currentColor" strokeWidth="2"/>
            </svg>
          )}
        </button>
      </div>

      <div className="hero-section">
        <div className="logo-badge">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5z" fill="#6366f1"/>
            <path d="M2 17l10 5 10-5" stroke="#818cf8" strokeWidth="2"/>
            <path d="M2 12l10 5 10-5" stroke="#a5b4fc" strokeWidth="2"/>
          </svg>
        </div>
        <h1 className="app-title">AI 助手</h1>
        <p className="app-subtitle">管理您的 AI 模型与小说库</p>
      </div>

      <div className="tab-navigation">
        <button 
          className={`tab-btn ${activeTab === 'models' ? 'active' : ''}`}
          onClick={() => setActiveTab('models')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" strokeWidth="2"/>
            <path d="M2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2"/>
          </svg>
          模型配置
        </button>
        <button 
          className={`tab-btn ${activeTab === 'novels' ? 'active' : ''}`}
          onClick={() => setActiveTab('novels')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="2"/>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="2"/>
          </svg>
          小说管理
        </button>
      </div>

      {activeTab === 'models' ? (
        <div className="settings-content">
          <ConfigList
            configs={configs}
            selectedId={selectedConfigId}
            onSelect={setSelectedConfigId}
            onToggle={handleToggle}
            onDelete={handleDelete}
          />
          
          <div className="editor-panel">
            {selectedConfigId === null ? (
              <ConfigEditor
                config={null}
                onSave={handleSave}
                onTest={() => {}}
              />
            ) : selectedConfig ? (
              <ConfigEditor
                key={selectedConfig.id}
                config={selectedConfig}
                onSave={handleSave}
                onTest={() => {}}
              />
            ) : (
              <ConfigEditor
                config={null}
                onSave={handleSave}
                onTest={() => {}}
              />
            )}
            
            <button className="new-config-btn" onClick={handleNewConfig}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2"/>
              </svg>
              添加新模型
            </button>
          </div>
        </div>
      ) : (
        <div className="novels-content">
          {viewMode === 'detail' ? (
            <NovelDetail
              novelId={selectedNovelId}
              onBack={handleNovelBack}
              refetch={refetchNovels}
              onStartReading={handleStartReading}
            />
          ) : (
            <NovelList
              novels={novels}
              onSelect={handleNovelSelect}
              onDelete={() => {}}
              refetch={refetchNovels}
              onStartReading={handleStartReading}
            />
          )}
        </div>
      )}

      <div className="footer">
        <p>最后更新: {new Date().toLocaleTimeString()}</p>
        <p className="version">前端版本 v1.1.0</p>
      </div>
    </div>
  );
}

export default App;