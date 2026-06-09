// 新建 AI 创作项目 — AI 引导式问答 (动态版 + 轮播式 UI)
// 首题: 静态种子 (genre), 立即可见
// 后续每题: 由 LLM 基于历史动态生成 4~8 个选项
// 界面: 固定高度轮播; 顶部页码 1·2·3·4 + 「够了, 开始生成」; 左右滑动 / 点击页码 / 键盘 ←→ 切换
// 每个选项可点选, 也可在「其它」中输入自定义内容
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../../api/client.js';

// ---------- 常量 ----------
// 种子题: 让首屏立即可见, 不阻塞 LLM
const SEED_QUESTION = {
  question: '你想写什么类型的故事?',
  description: '可多选; AI 会据此动态出后续题目. 也可在「其它」中自定义.',
  options: [
    '玄幻', '都市', '悬疑', '科幻', '历史',
    '武侠', '言情', '军事', '游戏', '末世',
    '由 AI 决定',
  ],
  multiple: true,
  allow_custom: true,
};

const CUSTOM_MARKER = '__custom__';
const AI_DECIDE = '由 AI 决定';

// 高级设置: 范围 / 步长 / 默认值
const TEMP_MIN = 0;
const TEMP_MAX = 2;
const TEMP_STEP = 0.05;
const TEMP_DEFAULT = 0.6;
const MAX_TOKENS_MIN = 256;
const MAX_TOKENS_MAX = 8000;
const MAX_TOKENS_STEP = 64;
const MAX_TOKENS_DEFAULT = 1500;

// 轮播固定高度
const CAROUSEL_HEIGHT = 540;
// 程序化滚动时, 屏蔽 onScroll 触发的回写 (避免循环)
const SCROLL_LOCK_MS = 500;

// ---------- 工具函数 ----------
function isAnswered(choice, customText) {
  if (customText && customText.trim()) return true;
  if (choice === null || choice === undefined || choice === '') return false;
  if (Array.isArray(choice) && choice.length === 0) return false;
  return true;
}

function cleanChoice(choice) {
  if (Array.isArray(choice)) {
    const filtered = choice.filter((x) => x !== CUSTOM_MARKER);
    return filtered.length === 0 ? null : filtered;
  }
  if (choice === CUSTOM_MARKER) return null;
  return choice;
}

function answerToText(answer) {
  const c = answer?.choice;
  const t = (answer?.custom_text || '').trim();
  let main = '';
  if (Array.isArray(c)) main = c.filter((x) => x !== CUSTOM_MARKER).join(' / ');
  else if (c && c !== CUSTOM_MARKER) main = String(c);
  if (t) main = main ? `${main} · ${t}` : t;
  return main;
}

// ---------- 高级设置面板 ----------
function SettingsPanel({ models = [], settings, onChange, disabled = false }) {
  const {
    modelId,
    useCustomTemp,
    temperature,
    useCustomTokens,
    maxTokens,
  } = settings;

  const set = (patch) => onChange({ ...settings, ...patch });

  const chatModels = (models || []).filter(
    (m) => (m.capability || 'chat') === 'chat' && m.enabled
  );

  const effectiveModel = modelId
    ? (chatModels.find((m) => String(m.id) === String(modelId)) || {}).name || '已选模型'
    : '系统默认 (首个可用 chat 模型)';

  const dirty = !!modelId || useCustomTemp || useCustomTokens;

  return (
    <details className="intake-settings" open={dirty || undefined}>
      <summary>
        <span className="intake-settings-icon">⚙</span>
        <span>高级设置</span>
        <span className="intake-settings-status muted small">
          {dirty ? '已自定义' : '使用默认'}
        </span>
      </summary>
      <div className="intake-settings-body">
        <div className="form-row form-row-2">
          <div>
            <label className="form-label">AI 模型</label>
            <select
              className="form-input"
              value={modelId ?? ''}
              onChange={(e) =>
                set({ modelId: e.target.value ? Number(e.target.value) : null })
              }
              disabled={disabled}
            >
              <option value="">系统默认 (首个可用 chat 模型)</option>
              {chatModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.model_name})
                </option>
              ))}
            </select>
            <p className="muted small intake-settings-hint">当前: {effectiveModel}</p>
          </div>

          <div>
            <label className="form-label">
              采样温度 (temperature):{' '}
              <strong>{useCustomTemp ? Number(temperature).toFixed(2) : '默认'}</strong>
            </label>
            <div className="intake-settings-row">
              <input
                type="range"
                min={TEMP_MIN}
                max={TEMP_MAX}
                step={TEMP_STEP}
                value={temperature ?? TEMP_DEFAULT}
                onChange={(e) => set({ temperature: Number(e.target.value) })}
                disabled={disabled || !useCustomTemp}
                style={{ flex: 1 }}
              />
              <label className="intake-settings-toggle">
                <input
                  type="checkbox"
                  checked={useCustomTemp}
                  onChange={(e) => set({ useCustomTemp: e.target.checked })}
                  disabled={disabled}
                />
                自定义
              </label>
            </div>
            <p className="muted small intake-settings-hint">
              {useCustomTemp
                ? '当前生效: ' + Number(temperature).toFixed(2) + ' · 越低越稳定, 越高越发散'
                : '当前: 沿用 prompt 模板默认'}
            </p>
          </div>
        </div>

        <div className="form-row">
          <label className="form-label">
            最大输出 tokens:{' '}
            <strong>{useCustomTokens ? `${maxTokens} tokens` : '默认'}</strong>
          </label>
          <div className="intake-settings-row">
            <input
              type="range"
              min={MAX_TOKENS_MIN}
              max={MAX_TOKENS_MAX}
              step={MAX_TOKENS_STEP}
              value={maxTokens ?? MAX_TOKENS_DEFAULT}
              onChange={(e) => set({ maxTokens: Number(e.target.value) })}
              disabled={disabled || !useCustomTokens}
              style={{ flex: 1 }}
            />
            <label className="intake-settings-toggle">
              <input
                type="checkbox"
                checked={useCustomTokens}
                onChange={(e) => set({ useCustomTokens: e.target.checked })}
                disabled={disabled}
              />
              自定义
            </label>
          </div>
          <p className="muted small intake-settings-hint">
            {useCustomTokens
              ? `当前生效: ${maxTokens} tokens · AI 单次回复的最大长度`
              : `当前: 沿用 prompt 模板默认 (范围 ${MAX_TOKENS_MIN}~${MAX_TOKENS_MAX})`}
          </p>
        </div>

        {dirty && (
          <div className="intake-settings-foot">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() =>
                onChange({
                  modelId: null,
                  useCustomTemp: false,
                  temperature: TEMP_DEFAULT,
                  useCustomTokens: false,
                  maxTokens: MAX_TOKENS_DEFAULT,
                })
              }
              disabled={disabled}
            >
              重置为默认
            </button>
          </div>
        )}
      </div>
    </details>
  );
}

const DEFAULT_SETTINGS = {
  modelId: null,
  useCustomTemp: false,
  temperature: TEMP_DEFAULT,
  useCustomTokens: false,
  maxTokens: MAX_TOKENS_DEFAULT,
};

// ---------- 单题渲染 (可复用, 适合放轮播 slide) ----------
function QuestionStep({
  item,
  value,
  onChange,
  onPrev,
  onNext,
  onSkip,
  onFinish,
  isFirst,
  isLast,
  isLoadingNext,
  stepNo,
  totalAnswered,
}) {
  const multi = !!item.multiple;
  const allowCustom = item.allow_custom !== false;
  const current = Array.isArray(value.choice)
    ? value.choice
    : (value.choice ? [value.choice] : []);
  const customText = value.custom_text || '';
  const customSelected = current.includes(CUSTOM_MARKER);

  const toggleOption = (v) => {
    if (multi) {
      const has = current.includes(v);
      const next = has ? current.filter((x) => x !== v) : [...current, v];
      const cleaned = next.includes(AI_DECIDE)
        ? [AI_DECIDE]
        : next.filter((x) => x !== CUSTOM_MARKER);
      onChange({ choice: cleaned, custom_text: customText });
    } else {
      const next = current[0] === v ? '' : v;
      onChange({ choice: next, custom_text: customText });
    }
  };

  const toggleCustom = () => {
    if (multi) {
      const next = customSelected
        ? current.filter((x) => x !== CUSTOM_MARKER)
        : [...current.filter((x) => x !== AI_DECIDE), CUSTOM_MARKER];
      onChange({ choice: next, custom_text: customText });
    } else {
      onChange({
        choice: customSelected ? '' : CUSTOM_MARKER,
        custom_text: customText,
      });
    }
  };

  const setCustomText = (t) => onChange({ choice: value.choice, custom_text: t });

  return (
    <div className="intake-question">
      <div className="intake-step-meta muted small">
        第 {stepNo} 题 · 已完成 {totalAnswered} 题
      </div>
      <h3 className="intake-question-label">{item.question}</h3>
      {item.description && (
        <p className="intake-question-desc muted small">{item.description}</p>
      )}

      <div className="intake-options">
        {item.options.map((opt) => {
          const checked = multi ? current.includes(opt) : current[0] === opt;
          const isAI = opt === AI_DECIDE;
          return (
            <label
              key={opt}
              className={`intake-option ${checked ? 'selected' : ''} ${isAI ? 'intake-option-ai' : ''}`}
            >
              <input
                type={multi ? 'checkbox' : 'radio'}
                name={`q-${stepNo}`}
                value={opt}
                checked={checked}
                onChange={() => toggleOption(opt)}
              />
              <span className="intake-option-text">{opt}</span>
            </label>
          );
        })}
        {allowCustom && (
          <label
            className={`intake-option intake-option-custom ${customSelected ? 'selected' : ''}`}
          >
            <input
              type={multi ? 'checkbox' : 'radio'}
              name={`q-${stepNo}`}
              checked={customSelected}
              onChange={toggleCustom}
            />
            <span className="intake-option-text">其它 (自行输入)</span>
          </label>
        )}
      </div>

      {(customSelected || (!multi && item.options.length === 0)) && (
        <textarea
          className="form-input form-textarea intake-freetext"
          rows={3}
          placeholder={
            multi
              ? '输入自定义选项 (可写多个, 用「/」分隔)'
              : '输入自定义内容...'
          }
          value={customText}
          onChange={(e) => setCustomText(e.target.value)}
        />
      )}

      <div className="intake-actions">
        <button
          type="button"
          className="btn btn-ghost"
          onClick={onPrev}
          disabled={isFirst || isLoadingNext}
        >
          上一步
        </button>
        {!isFirst && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onSkip}
            disabled={isLoadingNext}
          >
            跳过
          </button>
        )}
        <button
          type="button"
          className="btn btn-primary"
          onClick={onNext}
          disabled={isLoadingNext || !isAnswered(value.choice, customText)}
        >
          {isLoadingNext
            ? (isLast ? '综合中...' : '出题中...')
            : (isLast ? '完成并生成' : '下一步')}
        </button>
      </div>
    </div>
  );
}

// ---------- 草稿预览 ----------
function PreviewStep({
  draft,
  modelLabel,
  onChange,
  onPrev,
  onSubmit,
  onRegenerate,
  submitting,
  regenerating,
}) {
  const update = (k, v) => onChange({ ...draft, [k]: v });
  const updateStyle = (k, v) =>
    onChange({ ...draft, style_pref: { ...(draft.style_pref || {}), [k]: v } });
  const updateConcept = (idx, patch) => {
    const list = (draft.initial_concepts || []).map((c, i) =>
      i === idx ? { ...c, ...patch } : c
    );
    onChange({ ...draft, initial_concepts: list });
  };
  const addConcept = () => {
    const list = [...(draft.initial_concepts || []), { name: '', attributes: {} }];
    onChange({ ...draft, initial_concepts: list });
  };
  const removeConcept = (idx) => {
    const list = (draft.initial_concepts || []).filter((_, i) => i !== idx);
    onChange({ ...draft, initial_concepts: list });
  };

  return (
    <div className="intake-preview">
      <div className="intake-step-meta muted small">
        AI 已根据你的选择生成项目草稿, 可在下方直接修改后再创建.
      </div>
      <div className="intake-preview-grid">
        <div className="form-row">
          <label className="form-label">标题 <span className="required">*</span></label>
          <input
            type="text"
            className="form-input"
            value={draft.title || ''}
            onChange={(e) => update('title', e.target.value)}
            maxLength={200}
            placeholder="如: 长安秘事"
          />
        </div>

        <div className="form-row form-row-2">
          <div>
            <label className="form-label">类型</label>
            <input
              type="text"
              className="form-input"
              value={draft.genre || ''}
              onChange={(e) => update('genre', e.target.value)}
              maxLength={200}
              placeholder="如: 玄幻/修仙"
            />
          </div>
          <div>
            <label className="form-label">使用模型</label>
            <input
              type="text"
              className="form-input"
              value={modelLabel || '系统默认 (首个可用 chat 模型)'}
              readOnly
              title="模型在「高级设置」中配置, 此处只读"
            />
            <p className="muted small intake-settings-hint">
              如需更换, 请点击上方的「高级设置」调整
            </p>
          </div>
        </div>

        <div className="form-row">
          <label className="form-label">世界观 / 设定</label>
          <textarea
            className="form-input form-textarea"
            rows={3}
            value={draft.worldview || ''}
            onChange={(e) => update('worldview', e.target.value)}
            placeholder="时代背景 / 地理 / 力量体系 / 势力格局..."
          />
        </div>

        <div className="form-row">
          <label className="form-label">总纲 / 故事走向</label>
          <textarea
            className="form-input form-textarea"
            rows={4}
            value={draft.outline || ''}
            onChange={(e) => update('outline', e.target.value)}
            placeholder="主线 + 主角起点 + 主要冲突 + 走向"
          />
        </div>

        <div className="form-row">
          <label className="form-label">初始人物 (可后续从「设定」导入)</label>
          <div className="creation-concepts">
            {(draft.initial_concepts || []).length === 0 ? (
              <p className="muted small">还没有人物, 点击下方添加</p>
            ) : (
              draft.initial_concepts.map((c, i) => (
                <div key={i} className="creation-concept-row">
                  <input
                    type="text"
                    className="form-input"
                    placeholder={`人物 ${i + 1} 名字`}
                    value={c.name || ''}
                    onChange={(e) => updateConcept(i, { name: e.target.value })}
                  />
                  <input
                    type="text"
                    className="form-input"
                    placeholder="身份/性格 (自由填写)"
                    value={Object.entries(c.attributes || {})
                      .map(([k, v]) => `${k}=${v}`)
                      .join('; ')}
                    onChange={(e) => {
                      const txt = e.target.value;
                      const attrs = {};
                      txt.split(';')
                        .map((s) => s.trim())
                        .filter(Boolean)
                        .forEach((kv) => {
                          const [k, ...rest] = kv.split('=');
                          if (k && rest.length) attrs[k.trim()] = rest.join('=').trim();
                        });
                      updateConcept(i, { attributes: attrs });
                    }}
                  />
                  <button
                    type="button"
                    className="icon-btn"
                    onClick={() => removeConcept(i)}
                    title="删除该人物"
                    aria-label="删除"
                  >
                    ×
                  </button>
                </div>
              ))
            )}
            <button type="button" className="btn btn-ghost btn-sm" onClick={addConcept}>
              + 添加人物
            </button>
          </div>
        </div>

        <div className="form-row form-row-2">
          <div>
            <label className="form-label">叙述视角</label>
            <select
              className="form-input"
              value={draft.style_pref?.视角 || '第三人称'}
              onChange={(e) => updateStyle('视角', e.target.value)}
            >
              <option value="第一人称">第一人称</option>
              <option value="第三人称">第三人称</option>
              <option value="全知视角">全知视角</option>
            </select>
          </div>
          <div>
            <label className="form-label">语气 / 文风</label>
            <input
              type="text"
              className="form-input"
              value={draft.style_pref?.语气 || ''}
              onChange={(e) => updateStyle('语气', e.target.value)}
              placeholder="如: 热血 / 冷峻 / 文艺 / 幽默"
            />
          </div>
        </div>
      </div>

      {draft.raw && (
        <details className="intake-raw-debug">
          <summary className="muted small">查看 LLM 原始输出 (调试用)</summary>
          <pre>{draft.raw}</pre>
        </details>
      )}
      {draft.model_name && (
        <p className="muted small">综合模型: {draft.model_name}</p>
      )}

      <div className="intake-actions">
        <button type="button" className="btn btn-ghost" onClick={onPrev} disabled={submitting}>
          返回问答
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={onRegenerate}
          disabled={regenerating || submitting}
        >
          {regenerating ? '重新生成中...' : '重新生成草稿'}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={onSubmit}
          disabled={submitting || !(draft.title || '').trim()}
        >
          {submitting ? '创建中...' : '确认创建项目'}
        </button>
      </div>
    </div>
  );
}

// ---------- 主组件: 轮播式 wizard ----------
export function ProjectIntakeWizard({
  models = [],
  onSubmit,
  onCancel,
  submitting = false,
}) {
  // slides: [{ spec, answer }]; 0 = 种子题; N+1 由 /next 动态追加
  const [slides, setSlides] = useState([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [loadingNext, setLoadingNext] = useState(false);
  const [phase, setPhase] = useState('starting'); // starting|asking|fetching|synthesizing|preview|error
  const [draft, setDraft] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [regenerating, setRegenerating] = useState(false);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);

  const trackRef = useRef(null);
  const scrollLockRef = useRef(false);
  const scrollLockTimerRef = useRef(null);

  // 高级设置 → API 覆盖字段
  const buildIntakeOverrides = () => {
    const out = { model_id: settings.modelId ?? null };
    if (settings.useCustomTemp && settings.temperature !== null && settings.temperature !== undefined) {
      out.temperature = Number(settings.temperature);
    }
    if (settings.useCustomTokens && settings.maxTokens !== null && settings.maxTokens !== undefined) {
      out.max_tokens = Number(settings.maxTokens);
    }
    return out;
  };

  // slides → 后端 history items
  const buildHistory = (sList) => sList.map((s) => ({
    question: s.spec.question,
    options: Array.isArray(s.spec.options) ? s.spec.options : [],
    choice: cleanChoice(s.answer?.choice),
    custom_text: (s.answer?.custom_text || '').trim(),
    multiple: !!s.spec.multiple,
    is_seed: !!s.spec.is_seed,
  }));

  // 初始化: 第一题为种子题
  useEffect(() => {
    setSlides([{
      spec: { ...SEED_QUESTION, is_seed: true },
      answer: { choice: null, custom_text: '' },
    }]);
    setCurrentIdx(0);
    setPhase('asking');
  }, []);

  // currentIdx 变化 → 程序化滚动到对应 slide
  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    const w = track.clientWidth;
    if (w === 0) return;
    scrollLockRef.current = true;
    if (scrollLockTimerRef.current) clearTimeout(scrollLockTimerRef.current);
    track.scrollTo({ left: currentIdx * w, behavior: 'smooth' });
    scrollLockTimerRef.current = setTimeout(() => {
      scrollLockRef.current = false;
    }, SCROLL_LOCK_MS);
    return () => {
      if (scrollLockTimerRef.current) clearTimeout(scrollLockTimerRef.current);
    };
  }, [currentIdx, slides.length]);

  // 监听用户滑动 → 回写到 currentIdx
  const handleTrackScroll = () => {
    if (scrollLockRef.current) return;
    const track = trackRef.current;
    if (!track) return;
    const w = track.clientWidth;
    if (w === 0) return;
    const idx = Math.round(track.scrollLeft / w);
    if (idx >= 0 && idx < slides.length && idx !== currentIdx) {
      setCurrentIdx(idx);
    }
  };

  // 键盘 ←→ 切换 (在非输入控件聚焦时)
  useEffect(() => {
    const onKey = (e) => {
      if (phase !== 'asking' && phase !== 'fetching') return;
      const tag = (e.target?.tagName || '').toUpperCase();
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        if (currentIdx > 0) setCurrentIdx(currentIdx - 1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        if (currentIdx < slides.length - 1) setCurrentIdx(currentIdx + 1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [phase, currentIdx, slides.length]);

  // 当前 slide 的回答变更
  const handleAnswerChange = (val) => {
    setSlides((prev) => prev.map((s, i) => (i === currentIdx ? { ...s, answer: val } : s)));
  };

  const goTo = (idx) => {
    if (idx < 0 || idx >= slides.length) return;
    if (idx !== currentIdx) setCurrentIdx(idx);
  };

  const goBack = () => {
    if (currentIdx > 0) setCurrentIdx(currentIdx - 1);
  };

  // 推进: 已有则跳, 否则拉下一题
  const advance = async () => {
    if (currentIdx + 1 < slides.length) {
      setCurrentIdx(currentIdx + 1);
      return;
    }
    await fetchAndAppendNext();
  };

  // 跳过当前题 (不回答, 直接推进)
  const skipCurrent = async () => {
    handleAnswerChange({ choice: null, custom_text: '' });
    await advance();
  };

  // 拉取下一题
  const fetchAndAppendNext = async () => {
    setLoadingNext(true);
    try {
      const history = buildHistory(slides);
      const resp = await api.creation.intakeNext({
        items: history,
        ...buildIntakeOverrides(),
      });
      if (resp.done) {
        await runSynthesize(history);
        return;
      }
      const newSlide = {
        spec: {
          question: resp.question,
          description: resp.description || '',
          options: Array.isArray(resp.options) ? resp.options : [],
          multiple: !!resp.multiple,
          allow_custom: resp.allow_custom !== false,
          is_seed: false,
        },
        answer: { choice: null, custom_text: '' },
      };
      setSlides((prev) => [...prev, newSlide]);
      setCurrentIdx((idx) => idx + 1);
    } catch (e) {
      setErrorMsg(e instanceof ApiError ? e.message : '获取下一题失败');
      setPhase('error');
    } finally {
      setLoadingNext(false);
    }
  };

  // 提前结束, 进入综合
  const finishEarly = async () => {
    const history = buildHistory(slides);
    await runSynthesize(history);
  };

  // 综合草稿
  const runSynthesize = async (hist) => {
    setPhase('synthesizing');
    setErrorMsg('');
    try {
      const resp = await api.creation.intakeSynthesize({
        items: hist,
        ...buildIntakeOverrides(),
      });
      const finalModelId = settings.modelId ?? resp.model_id ?? null;
      setDraft({
        title: resp.title || '',
        genre: resp.genre || '',
        worldview: resp.worldview || '',
        outline: resp.outline || '',
        initial_concepts: Array.isArray(resp.initial_concepts) ? resp.initial_concepts : [],
        style_pref: resp.style_pref || {},
        model_id: finalModelId,
        model_name: resp.model_name || null,
        raw: resp.raw || null,
      });
      setPhase('preview');
    } catch (e) {
      setErrorMsg(e instanceof ApiError ? e.message : '综合项目草稿失败');
      setPhase('error');
    }
  };

  const handleConfirmCreate = () => {
    if (!draft) return;
    onSubmit({
      title: (draft.title || '').trim(),
      genre: draft.genre || '',
      worldview: draft.worldview || '',
      outline: draft.outline || '',
      initial_concepts: (draft.initial_concepts || []).filter((c) => (c.name || '').trim()),
      style_pref: draft.style_pref || {},
      model_id: draft.model_id ?? null,
    });
  };

  // 已答数 (用于页码小圆点的状态展示)
  const answeredCount = useMemo(
    () => slides.filter((s) => isAnswered(s.answer?.choice, s.answer?.custom_text)).length,
    [slides]
  );

  // ---- 渲染 ----
  return (
    <div className="creation-intake-wizard">
      {phase !== 'starting' && (
        <SettingsPanel
          models={models}
          settings={settings}
          onChange={setSettings}
          disabled={loadingNext || phase === 'synthesizing' || regenerating}
        />
      )}

      {phase === 'starting' && (
        <div className="intake-loading">
          <div className="intake-spinner" />
          <p>准备开始引导式问答...</p>
        </div>
      )}

      {(phase === 'asking' || phase === 'fetching') && (
        <div
          className="intake-carousel"
          style={{ height: CAROUSEL_HEIGHT }}
        >
          {/* 顶部: 页码 + 结束按钮 */}
          <div className="intake-pages">
            {slides.map((s, i) => {
              const isCur = i === currentIdx;
              const isAns = isAnswered(s.answer?.choice, s.answer?.custom_text);
              return (
                <button
                  key={i}
                  type="button"
                  className={
                    'intake-page-dot'
                    + (isCur ? ' active' : '')
                    + (isAns ? ' done' : '')
                  }
                  onClick={() => goTo(i)}
                  title={`第 ${i + 1} 题${isAns ? ' · 已答' : ''}`}
                  aria-label={`跳到第 ${i + 1} 题`}
                >
                  {isAns && !isCur ? '✓' : i + 1}
                </button>
              );
            })}
            {loadingNext && currentIdx === slides.length - 1 && (
              <span className="intake-page-dot loading" title="AI 正在生成下一题">
                ···
              </span>
            )}
            <div className="intake-pages-spacer" />
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={finishEarly}
              disabled={loadingNext || slides.length === 0}
              title="把当前所有回答交给 AI 综合, 生成项目草稿"
            >
              够了, 开始生成
            </button>
          </div>

          {/* 主体: 横向滑动轨道 */}
          <div
            className="intake-carousel-track"
            ref={trackRef}
            onScroll={handleTrackScroll}
            role="region"
            aria-label="引导式问答"
          >
            {slides.map((s, i) => {
              const isCur = i === currentIdx;
              return (
                <div className="intake-slide" key={i} aria-hidden={!isCur}>
                  <div className="intake-slide-body">
                    <QuestionStep
                      item={s.spec}
                      value={s.answer}
                      onChange={handleAnswerChange}
                      onPrev={goBack}
                      onNext={advance}
                      onSkip={skipCurrent}
                      onFinish={finishEarly}
                      isFirst={i === 0}
                      isLast={i === slides.length - 1 && !loadingNext}
                      isLoadingNext={loadingNext}
                      stepNo={i + 1}
                      totalAnswered={answeredCount}
                    />
                  </div>
                </div>
              );
            })}
            {loadingNext && currentIdx === slides.length - 1 && (
              <div className="intake-slide" key="__loading__" aria-hidden="true">
                <div className="intake-slide-loading">
                  <div className="intake-spinner" />
                  <p>AI 正在生成下一题...</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {phase === 'synthesizing' && (
        <div className="intake-loading">
          <div className="intake-spinner" />
          <p>AI 正在综合你的全部回答, 生成项目草稿...</p>
          <p className="muted small">已完成 {answeredCount} / {slides.length} 题</p>
        </div>
      )}

      {phase === 'error' && (
        <div className="intake-error">
          <p className="creation-error small">出错了: {errorMsg}</p>
          <div className="intake-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setErrorMsg('');
                setPhase('asking');
              }}
            >
              返回
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                if (slides.length > 0) {
                  if (currentIdx === slides.length - 1) {
                    fetchAndAppendNext();
                  } else {
                    advance();
                  }
                } else {
                  runSynthesize([]);
                }
              }}
            >
              重试
            </button>
          </div>
        </div>
      )}

      {phase === 'preview' && draft && (
        <PreviewStep
          draft={draft}
          modelLabel={(() => {
            if (settings.modelId) {
              const m = (models || []).find(
                (mm) => String(mm.id) === String(settings.modelId)
              );
              if (m) return `${m.name} (${m.model_name})`;
              return '已选模型 (高级设置中)';
            }
            if (draft.model_name) return `系统默认 → ${draft.model_name}`;
            return '系统默认 (首个可用 chat 模型)';
          })()}
          onChange={setDraft}
          onPrev={() => setPhase('asking')}
          onSubmit={handleConfirmCreate}
          onRegenerate={async () => {
            setRegenerating(true);
            try {
              const hist = buildHistory(slides);
              const resp = await api.creation.intakeSynthesize({
                items: hist,
                ...buildIntakeOverrides(),
              });
              const finalModelId = settings.modelId ?? resp.model_id ?? null;
              setDraft({
                title: resp.title || '',
                genre: resp.genre || '',
                worldview: resp.worldview || '',
                outline: resp.outline || '',
                initial_concepts: Array.isArray(resp.initial_concepts) ? resp.initial_concepts : [],
                style_pref: resp.style_pref || {},
                model_id: finalModelId,
                model_name: resp.model_name || null,
                raw: resp.raw || null,
              });
            } catch (e) {
              setErrorMsg(e instanceof ApiError ? e.message : '重新生成失败');
            } finally {
              setRegenerating(false);
            }
          }}
          submitting={submitting}
          regenerating={regenerating}
        />
      )}

      <div className="intake-wizard-foot muted small">
        AI 引导式问答 · 已加载 {slides.length} 题 · 滑动 / 点击页码 / ← → 切换
      </div>
    </div>
  );
}
