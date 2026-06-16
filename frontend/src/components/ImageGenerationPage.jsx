import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';

// 持久化图像生成页面的"表单 + 最近结果", 让刷新/切页之后能直接续上.
// 引用图是二进制, 不进 localStorage; 用户重新进入页面只需重新上传.
const FORM_KEY = 'ainovel.imageGen.form.v1';
const RESULTS_KEY = 'ainovel.imageGen.results.v1';
const LAST_TASK_KEY = 'ainovel.imageGen.lastTask.v1';
const MAX_PERSISTED_RESULTS = 30; // 防止 localStorage 超限 (5MB / 项)

function readJSON(key, fallback) {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const data = JSON.parse(raw);
    return data ?? fallback;
  } catch {
    return fallback;
  }
}
function writeJSON(key, value) {
  if (typeof window === 'undefined') return;
  try {
    if (value == null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(value));
  } catch { /* noop */ }
}

// 修复 #33: schemaVersion — 字段未来加 / 改时, 旧数据能自动清掉而不会 crash.
// 每改一次持久化结构, 把 SCHEMA_VERSION + 1 并在 readJSONWithVersion 加
// 迁移规则即可. 当前 v1 = 初始结构.
const SCHEMA_VERSION = 1;

function readJSONWithVersion(key, fallback, schemaVersion) {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const wrapped = JSON.parse(raw);
    if (!wrapped || typeof wrapped !== 'object') return fallback;
    if (wrapped.__schema !== schemaVersion) {
      // 版本不匹配: 丢弃旧数据, 避免字段缺失/类型变更导致页面崩溃
      try { window.localStorage.removeItem(key); } catch { /* noop */ }
      return fallback;
    }
    return wrapped.data ?? fallback;
  } catch {
    return fallback;
  }
}

function writeJSONWithVersion(key, data, schemaVersion) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      key,
      JSON.stringify({ __schema: schemaVersion, data, __at: Date.now() })
    );
  } catch { /* noop */ }
}

const ASPECT_OPTIONS = [
  { value: '1:1', label: '1:1 (1024×1024)' },
  { value: '16:9', label: '16:9 (1280×720)' },
  { value: '4:3', label: '4:3 (1152×864)' },
  { value: '3:2', label: '3:2 (1248×832)' },
  { value: '2:3', label: '2:3 (832×1248)' },
  { value: '3:4', label: '3:4 (864×1152)' },
  { value: '9:16', label: '9:16 (720×1280)' },
  { value: '21:9', label: '21:9 (1344×576, 仅 image-01)' },
];

const STYLE_OPTIONS = [
  { value: '', label: '不指定' },
  { value: '漫画', label: '漫画' },
  { value: '元气', label: '元气' },
  { value: '中世纪', label: '中世纪' },
  { value: '水彩', label: '水彩' },
];

const MODE_OPTIONS = [
  {
    value: 'text',
    label: '文生图',
    description: '仅通过文字描述生成图像',
  },
  {
    value: 'image',
    label: '图生图',
    description: '上传参考图（人物主体）后再生成',
  },
];

function ResultCard({ item, index, onRemove }) {
  const src = item.url || (item.b64 ? `data:image/png;base64,${item.b64}` : null);
  if (!src) return null;
  return (
    <div className="image-result-card">
      <div className="image-result-thumb">
        <img src={src} alt={`生成结果 #${index + 1}`} loading="lazy" />
      </div>
      <div className="image-result-meta">
        <span className="image-result-index">#{index + 1}</span>
        <div className="image-result-actions">
          <a
            className="image-result-action"
            href={src}
            target="_blank"
            rel="noreferrer"
            download={`image-${Date.now()}-${index + 1}.${item.b64 ? 'png' : 'jpg'}`}
          >
            下载
          </a>
          <a
            className="image-result-action"
            href={src}
            target="_blank"
            rel="noreferrer"
          >
            新窗口打开
          </a>
          {onRemove && (
            <button
              type="button"
              className="image-result-action danger"
              onClick={() => onRemove(index)}
            >
              移除
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function ImageGenerationPage({ models }) {
  const toast = useToast();
  const [imageModels, setImageModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  // 模型选择也持久化, 默认值 fallback 为 null 由下方 effect 兜底
  const [selectedModelId, setSelectedModelId] = useState(() => {
    const saved = readJSON(FORM_KEY, null);
    return saved && saved.selectedModelId != null ? saved.selectedModelId : null;
  });

  const [mode, setMode] = useState(() => readJSON(FORM_KEY, { mode: 'text' }).mode || 'text');
  const [prompt, setPrompt] = useState(() => {
    const saved = readJSON(FORM_KEY, null);
    return saved && typeof saved.prompt === 'string'
      ? saved.prompt
      : '一位少女站在开满樱花的校园小路中央，午后阳光透过花瓣洒下，电影感构图';
  });
  const [negativePrompt, setNegativePrompt] = useState(() => {
    const saved = readJSON(FORM_KEY, null);
    return saved ? saved.negativePrompt || '' : '';
  });
  const [aspectRatio, setAspectRatio] = useState(() => readJSON(FORM_KEY, { aspectRatio: '1:1' }).aspectRatio);
  const [n, setN] = useState(() => Number(readJSON(FORM_KEY, { n: 1 }).n) || 1);
  const [seed, setSeed] = useState(() => {
    const saved = readJSON(FORM_KEY, null);
    return saved ? saved.seed || '' : '';
  });
  const [styleType, setStyleType] = useState(() => readJSON(FORM_KEY, { styleType: '' }).styleType);
  const [styleWeight, setStyleWeight] = useState(() => {
    const v = Number(readJSON(FORM_KEY, { styleWeight: 0.8 }).styleWeight);
    return Number.isFinite(v) ? v : 0.8;
  });
  const [promptOptimizer, setPromptOptimizer] = useState(() => Boolean(readJSON(FORM_KEY, { promptOptimizer: false }).promptOptimizer));
  const [aigcWatermark, setAigcWatermark] = useState(() => Boolean(readJSON(FORM_KEY, { aigcWatermark: false }).aigcWatermark));
  const [responseFormat, setResponseFormat] = useState(() => readJSON(FORM_KEY, { responseFormat: 'url' }).responseFormat);

  const [references, setReferences] = useState([]); // [{ name, size, dataUri, previewUrl }] — 二进制, 不进 localStorage
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);
  // 修复 #32: 页面内自管搜索
  const [search, setSearch] = useState('');

  const [generating, setGenerating] = useState(false);
  const [lastTask, setLastTask] = useState(() => readJSON(LAST_TASK_KEY, null));
  const [results, setResults] = useState(() => {
    // 修复 #33: 用 schemaVersion 包装读, 老格式 / 跨版本数据直接丢弃
    const saved = readJSONWithVersion(RESULTS_KEY, [], SCHEMA_VERSION);
    return Array.isArray(saved) ? saved : [];
  });
  const [error, setError] = useState(null);

  // 持久化: 任一表单字段变更都写一次 localStorage (合并写, 减少 IO).
  useEffect(() => {
    writeJSONWithVersion(FORM_KEY, {
      selectedModelId,
      mode,
      prompt,
      negativePrompt,
      aspectRatio,
      n,
      seed,
      styleType,
      styleWeight,
      promptOptimizer,
      aigcWatermark,
      responseFormat,
    }, SCHEMA_VERSION);
  }, [
    selectedModelId, mode, prompt, negativePrompt, aspectRatio, n, seed,
    styleType, styleWeight, promptOptimizer, aigcWatermark, responseFormat,
  ]);

  // 持久化最近一次任务的快照 + 历史结果 (截断)
  useEffect(() => {
    writeJSON(LAST_TASK_KEY, lastTask);
  }, [lastTask]);
  useEffect(() => {
    if (results.length === 0) {
      writeJSONWithVersion(RESULTS_KEY, null, SCHEMA_VERSION);
      return;
    }
    // 只保留最近 N 条, 防止 localStorage 5MB 限制
    writeJSONWithVersion(
      RESULTS_KEY,
      results.slice(0, MAX_PERSISTED_RESULTS),
      SCHEMA_VERSION,
    );
  }, [results]);

  // Filter to image-capable models from the page-level `models` prop.
  const allImageModels = useMemo(
    () => (models || []).filter((m) => (m.capability || 'chat') === 'image'),
    [models],
  );

  useEffect(() => {
    let cancelled = false;
    const fetchImageModels = async () => {
      setModelsLoading(true);
      try {
        const data = await api.image.listEnabledModels();
        if (!cancelled) {
          setImageModels(data || []);
          if (!selectedModelId && data && data.length > 0) {
            setSelectedModelId(data[0].id);
          }
        }
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载图像模型失败');
        }
      } finally {
        if (!cancelled) setModelsLoading(false);
      }
    };
    fetchImageModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the selected model in sync if the global list changes.
  useEffect(() => {
    if (!allImageModels.length) return;
    if (!selectedModelId || !allImageModels.find((m) => m.id === selectedModelId)) {
      setSelectedModelId(allImageModels[0].id);
    }
  }, [allImageModels, selectedModelId]);

  const filteredResults = useMemo(() => {
    // 修复 #32: 用组件内 search 状态而非外部 topSearch
    if (!search) return results;
    const k = search.toLowerCase();
    return results.filter((r) => (r.prompt || '').toLowerCase().includes(k));
  }, [results, search]);

  const handleReferenceUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setUploading(true);
    try {
      const newRefs = [];
      for (const file of files) {
        if (!file.type.startsWith('image/')) {
          toast.error(`不支持的文件类型: ${file.name}`);
          continue;
        }
        if (file.size > 10 * 1024 * 1024) {
          toast.error(`文件过大: ${file.name}（上限 10MB）`);
          continue;
        }
        const uploaded = await api.image.uploadReference(file);
        newRefs.push({
          name: file.name,
          size: file.size,
          dataUri: uploaded?.data_uri,
          previewUrl: uploaded?.url || uploaded?.data_uri,
          type: file.type,
        });
      }
      if (newRefs.length) {
        setReferences((prev) => [...prev, ...newRefs]);
        setMode('image');
      }
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleRemoveReference = (idx) => {
    setReferences((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleAddReferenceUrl = () => {
    const url = window.prompt('请输入参考图公网 URL（限 jpg/png/jpeg/webp，<10MB）');
    if (!url) return;
    if (!/^https?:\/\//i.test(url)) {
      toast.error('URL 必须以 http:// 或 https:// 开头');
      return;
    }
    setReferences((prev) => [...prev, {
      name: url,
      size: null,
      dataUri: url,
      previewUrl: url,
      isUrl: true,
    }]);
    setMode('image');
  };

  const handleGenerate = async () => {
    setError(null);
    if (!selectedModelId) {
      setError('请先在「系统设置 → 模型配置」中启用至少一个图像生成模型');
      return;
    }
    if (!prompt.trim()) {
      setError('请填写提示词');
      return;
    }
    if (mode === 'image' && references.length === 0) {
      setError('图生图模式需要至少一张参考图');
      return;
    }
    const payload = {
      model_config_id: selectedModelId,
      prompt: prompt.trim(),
      aspect_ratio: aspectRatio,
      n,
      response_format: responseFormat,
      prompt_optimizer: promptOptimizer,
      aigc_watermark: aigcWatermark,
    };
    if (negativePrompt.trim()) {
      payload.negative_prompt = negativePrompt.trim();
    }
    if (seed !== '' && !Number.isNaN(Number(seed))) {
      payload.seed = Number(seed);
    }
    if (styleType) {
      payload.style = { style_type: styleType, style_weight: Number(styleWeight) };
    }
    if (mode === 'image' && references.length > 0) {
      payload.subject_reference = references.map((r) => ({
        type: 'character',
        image_file: r.dataUri,
      }));
    }

    setGenerating(true);
    setLastTask(null);
    try {
      const resp = await api.image.generate(payload);
      if (!resp.success) {
        setError(resp.message || '生成失败');
        toast.error(resp.message || '生成失败');
        return;
      }
      setLastTask(resp);
      setResults((prev) => [...(resp.images || []), ...prev]);
      toast.success(
        `生成完成（成功 ${resp.success_count || (resp.images || []).length}${
          resp.failed_count ? `，失败 ${resp.failed_count}` : ''
        }）`,
      );
    } catch (err) {
      const message = err instanceof ApiError ? err.message : '生成失败';
      setError(message);
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  };

  const handleClear = () => {
    setResults([]);
    setLastTask(null);
    setError(null);
    // 同时清掉持久化, 避免下次进入又恢复
    writeJSONWithVersion(RESULTS_KEY, null, SCHEMA_VERSION);
    writeJSON(LAST_TASK_KEY, null);
  };

  const selectedModel = imageModels.find((m) => m.id === selectedModelId);

  return (
    <div className="image-generation-page">
      <div className="image-gen-header">
        <div>
          <h2>图像生成</h2>
          <p className="page-sub">
            基于 {imageModels.length > 0 ? `已启用的 ${imageModels.length} 个` : '图像生成模型'}
            ，支持文生图、图生图与多种风格。
          </p>
        </div>
        <div className="image-gen-header-actions">
          <button
            type="button"
            className="ghost-button"
            onClick={handleClear}
            disabled={!results.length || generating}
          >
            清空结果
          </button>
        </div>
      </div>

      {imageModels.length === 0 ? (
        <div className="image-gen-empty">
          <div className="empty-icon">🎨</div>
          <h3>还没有可用的图像生成模型</h3>
          <p>请前往「系统设置 → 模型配置」添加一个「图像生成」类型的模型并启用。</p>
          <p className="empty-hint">
            推荐：MiniMax（image-01 / image-01-live），Base URL 填写
            <code>https://api.minimaxi.com</code>。
          </p>
        </div>
      ) : (
        <div className="image-gen-grid">
          <section className="image-gen-form">
            <div className="form-group">
              <label>生成模式</label>
              <div className="image-mode-selector">
                {MODE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={`image-mode-option ${mode === opt.value ? 'selected' : ''}`}
                    onClick={() => setMode(opt.value)}
                  >
                    <span className="image-mode-label">{opt.label}</span>
                    <span className="image-mode-desc">{opt.description}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="form-group">
              <label>图像模型</label>
              <select
                value={selectedModelId || ''}
                onChange={(e) => setSelectedModelId(Number(e.target.value))}
              >
                {imageModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}（{m.model_name}）
                  </option>
                ))}
              </select>
              {selectedModel && (
                <span className="form-hint">Base URL: {selectedModel.model_url}</span>
              )}
            </div>

            <div className="form-group">
              <label>提示词 *</label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={5}
                placeholder="描述想要生成的画面，主体、构图、光线、风格等越具体效果越好"
                maxLength={1500}
              />
              <span className="form-hint">
                {prompt.length} / 1500
              </span>
            </div>

            <div className="form-group">
              <label>反向提示词（可选）</label>
              <textarea
                value={negativePrompt}
                onChange={(e) => setNegativePrompt(e.target.value)}
                rows={2}
                placeholder="不希望出现的内容，例如：模糊、畸形手指、低分辨率"
                maxLength={1500}
              />
              <span className="form-hint">
                阿里云 DashScope 等模型会使用此字段（parameters.negative_prompt）；MiniMax 暂不支持，会被忽略。
              </span>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>宽高比</label>
                <select
                  value={aspectRatio}
                  onChange={(e) => setAspectRatio(e.target.value)}
                >
                  {ASPECT_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>生成数量 (1-9)</label>
                <input
                  type="number"
                  min={1}
                  max={9}
                  value={n}
                  onChange={(e) => {
                    const v = Math.max(1, Math.min(9, Number(e.target.value) || 1));
                    setN(v);
                  }}
                />
              </div>
              <div className="form-group">
                <label>随机种子（可选）</label>
                <input
                  type="text"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value)}
                  placeholder="留空使用随机"
                />
              </div>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>画风（仅 image-01-live）</label>
                <select
                  value={styleType}
                  onChange={(e) => setStyleType(e.target.value)}
                >
                  {STYLE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              {styleType && (
                <div className="form-group">
                  <label>画风权重 ({(Number(styleWeight) || 0).toFixed(2)})</label>
                  <input
                    type="range"
                    min={0.1}
                    max={1}
                    step={0.05}
                    value={styleWeight}
                    onChange={(e) => setStyleWeight(Number(e.target.value))}
                  />
                </div>
              )}
            </div>

            <div className="form-row">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={promptOptimizer}
                  onChange={(e) => setPromptOptimizer(e.target.checked)}
                />
                <span>启用 Prompt 自动优化</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={aigcWatermark}
                  onChange={(e) => setAigcWatermark(e.target.checked)}
                />
                <span>添加 AIGC 水印</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={responseFormat === 'base64'}
                  onChange={(e) =>
                    setResponseFormat(e.target.checked ? 'base64' : 'url')
                  }
                />
                <span>返回 Base64（默认 URL，URL 24h 有效）</span>
              </label>
            </div>

            {mode === 'image' && (
              <div className="form-group">
                <label>主体参考图（人物）</label>
                <div className="reference-uploader">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/jpeg,image/jpg,image/png,image/webp"
                    multiple
                    onChange={handleReferenceUpload}
                    style={{ display: 'none' }}
                  />
                  <div className="reference-actions">
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                    >
                      {uploading ? '上传中…' : '上传本地图片'}
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={handleAddReferenceUrl}
                    >
                      使用公网 URL
                    </button>
                  </div>
                  <span className="form-hint">
                    支持 jpg/jpeg/png/webp，单张不超过 10MB。建议使用单人正面照片以获得最佳效果。
                  </span>
                  {references.length > 0 && (
                    <div className="reference-grid">
                      {references.map((ref, idx) => (
                        <div className="reference-thumb" key={`${ref.name}-${idx}`}>
                          <img src={ref.previewUrl || ref.dataUri} alt={ref.name} />
                          <button
                            type="button"
                            className="reference-remove"
                            onClick={() => handleRemoveReference(idx)}
                            title="移除"
                          >
                            ×
                          </button>
                          <span className="reference-name" title={ref.name}>
                            {ref.isUrl ? '🔗 ' : ''}
                            {ref.name}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className="form-group form-actions">
              <button
                type="button"
                className="primary-button"
                onClick={handleGenerate}
                disabled={generating}
              >
                {generating ? (
                  <>
                    <span className="loading-spinner"></span>
                    生成中…
                  </>
                ) : (
                  <>开始生成</>
                )}
              </button>
              {error && <span className="form-error">{error}</span>}
            </div>
          </section>

          <section className="image-gen-results">
            <div className="image-gen-results-header">
              <h3>生成结果</h3>
              <span className="image-gen-results-count">
                {results.length > 0 ? `共 ${results.length} 张` : '暂无结果'}
              </span>
            </div>
            {lastTask && (
              <div className="image-gen-task-info">
                <span>模型: {lastTask.model}</span>
                {lastTask.task_id && <span>任务 ID: {lastTask.task_id}</span>}
                <span>
                  成功 {lastTask.success_count || 0}
                  {lastTask.failed_count ? `，失败 ${lastTask.failed_count}` : ''}
                </span>
              </div>
            )}
            {filteredResults.length === 0 ? (
              <div className="image-gen-empty-results">
                {generating ? (
                  <>
                    <div className="loading-spinner large"></div>
                    <p>正在生成，请稍候…</p>
                  </>
                ) : (
                  <>
                    <p>填写左侧表单后点击「开始生成」</p>
                    <span>结果会按生成时间倒序展示，可下载或新窗口打开</span>
                  </>
                )}
              </div>
            ) : (
              <div className="image-results-grid">
                {filteredResults.map((item, idx) => (
                  <ResultCard
                    key={`${item.url || item.b64 || 'item'}-${idx}-${results.length}`}
                    item={item}
                    index={idx}
                    onRemove={(i) => {
                      // We can't reliably map filtered index → original; allow
                      // removal by recomputing against the source list.
                      const target = filteredResults[i];
                      setResults((prev) => {
                        const flat = prev;
                        const removeIdx = flat.indexOf(target);
                        if (removeIdx < 0) return prev;
                        const next = flat.slice();
                        next.splice(removeIdx, 1);
                        return next;
                      });
                    }}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
