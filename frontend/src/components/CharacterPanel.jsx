import { useEffect, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';

function ModelSelect({ models, value, onChange, disabled }) {
  const enabledModels = models.filter((m) => m.enabled);
  if (enabledModels.length === 0) {
    return (
      <div className="model-empty">
        请先在「系统设置」中启用至少一个 AI 模型
      </div>
    );
  }
  return (
    <select value={value || ''} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      <option value="">使用默认模型</option>
      {enabledModels.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name || m.provider} · {m.model_name}
        </option>
      ))}
    </select>
  );
}

function CharacterCard({ character, index }) {
  const initial = (character.name || '?').slice(0, 1);
  return (
    <article className="character-card">
      <div className="character-avatar" aria-hidden>
        {initial}
      </div>
      <div className="character-body">
        <header>
          <h4>{character.name}</h4>
          {character.role && <span className="character-role">{character.role}</span>}
        </header>
        {character.description && <p className="character-desc">{character.description}</p>}
        <div className="character-meta">
          {character.first_appearance && (
            <span className="character-tag">首现于第 {character.first_appearance} 章</span>
          )}
          {character.aliases?.length > 0 && (
            <span className="character-tag alt">
              别名：{character.aliases.join('、')}
            </span>
          )}
        </div>
      </div>
      <span className="character-index">#{index + 1}</span>
    </article>
  );
}

export function CharacterPanel({ novelId, models, novelTitle, onExtracted }) {
  const toast = useToast();
  const [characters, setCharacters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [modelConfigId, setModelConfigId] = useState('');
  const [maxChars, setMaxChars] = useState(8000);
  const [maxCharacters, setMaxCharacters] = useState(20);
  const [lastModel, setLastModel] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);

  const enabledModels = models.filter((m) => m.enabled);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const data = await api.novels.listCharacters(novelId);
        if (cancelled) return;
        setCharacters(data.characters || []);
        if (data.characters?.length) {
          setLastModel(data.characters.find((c) => c.model_id)?.model_id ?? null);
        }
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载人物失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [novelId, toast]);

  const handleExtract = async () => {
    if (enabledModels.length === 0) {
      toast.error('请先在「系统设置」中启用模型');
      return;
    }
    setExtracting(true);
    try {
      const result = await api.novels.extractCharacters(novelId, {
        model_config_id: modelConfigId ? Number(modelConfigId) : null,
        max_chars: Number(maxChars),
        max_characters: Number(maxCharacters),
      });
      setCharacters(result.characters || []);
      setLastModel(result.model || null);
      setUpdatedAt(new Date().toLocaleTimeString());
      if (result.characters?.length) {
        toast.success(result.message || `已识别 ${result.characters.length} 位人物`);
      } else {
        toast.info(result.message || '未识别到明显人物，可尝试调整参数');
      }
      onExtracted?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '人物提取失败');
    } finally {
      setExtracting(false);
    }
  };

  return (
    <div className="character-panel">
      <div className="character-toolbar">
        <div className="toolbar-field">
          <label>AI 模型</label>
          <ModelSelect
            models={models}
            value={modelConfigId}
            onChange={setModelConfigId}
            disabled={extracting}
          />
        </div>
        <div className="toolbar-field small">
          <label>分析字数</label>
          <select
            value={maxChars}
            onChange={(e) => setMaxChars(Number(e.target.value))}
            disabled={extracting}
          >
            <option value={4000}>4000 字</option>
            <option value={8000}>8000 字</option>
            <option value={16000}>16000 字</option>
            <option value={32000}>32000 字</option>
          </select>
        </div>
        <div className="toolbar-field small">
          <label>最多人物</label>
          <input
            type="number"
            min={1}
            max={100}
            value={maxCharacters}
            onChange={(e) => setMaxCharacters(Number(e.target.value) || 1)}
            disabled={extracting}
          />
        </div>
        <button
          type="button"
          className="extract-btn"
          onClick={handleExtract}
          disabled={extracting || enabledModels.length === 0}
        >
          {extracting ? (
            <>
              <span className="loading-spinner small"></span>
              提取中...
            </>
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path
                  d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              提取人物
            </>
          )}
        </button>
      </div>

      <div className="character-summary">
        <div>
          <span className="summary-label">已识别</span>
          <strong>{characters.length}</strong>
          <span className="summary-unit">位</span>
        </div>
        {lastModel && (
          <div className="summary-sub">
            <span>使用模型：</span>
            <strong>{lastModel}</strong>
          </div>
        )}
        {updatedAt && (
          <div className="summary-sub">更新于 {updatedAt}</div>
        )}
      </div>

      {loading ? (
        <div className="loading-block">
          <div className="loading-spinner large"></div>
          <p>加载人物列表...</p>
        </div>
      ) : characters.length === 0 ? (
        <div className="character-empty">
          <svg width="56" height="56" viewBox="0 0 24 24" fill="none">
            <path
              d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <p>「{novelTitle}」暂无人物档案</p>
          <span>点击「提取人物」让 AI 帮你梳理出场角色</span>
        </div>
      ) : (
        <div className="character-grid">
          {characters.map((c, i) => (
            <CharacterCard key={c.id ?? `${c.name}-${i}`} character={c} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
