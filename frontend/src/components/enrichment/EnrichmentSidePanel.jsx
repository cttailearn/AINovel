import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../../api/client.js';
import { useToast } from '../Toast/ToastProvider.jsx';
import {
  EditableField,
  EditableListField,
  SceneTagField,
} from './EditableField.jsx';
import { ContextPreview } from './ContextPreview.jsx';
import { HighlightedReader } from './HighlightedReader.jsx';
import { MergedReader } from './MergedReader.jsx';
import { SideBySideReader } from './SideBySideReader.jsx';

const SCENE_OPTIONS = [
  '高燃战斗', '日常', '权谋', '言情', '悬疑', '惊悚',
  '修炼', '校园', '宫廷', '江湖', '玄幻', '科幻',
  '历史', '末世', '推理', '商战', '其他',
];

/** 预设的「加料需求」模板 */
const INTENT_PRESETS = [
  { label: '增加战斗动作与心理描写', text: '在战斗 / 冲突段落增加动作细节与人物心理描写, 强化紧张感' },
  { label: '对话更口语化', text: '把对话改得更口语化、生活化, 符合人物身份, 减少书面语' },
  { label: '增加 200 字情绪段落', text: '在高潮段落增加 200 字左右的情绪渲染和内心独白' },
  { label: '增加景物烘托', text: '保留原意, 但在场景切换处增加景物 / 氛围烘托描写' },
  { label: '人物塑造强化', text: '通过动作 / 语言 / 心理的细节, 强化主要人物的形象特征' },
];

/**
 * 「AI 加料工坊」侧栏 (v0.2.1 重构)
 * 3 步向导:
 *  - Step 1 拆解 (Context Builder) - 概要 / 场景 / 人物 / 事件 均可编辑
 *  - Step 2 加料需求 (Intent)      - 多行文本 + 预设
 *  - Step 3 生成与比对              - 生成 / 4 种预览 / 应用 / 回滚 / 历史
 */
export function EnrichmentSidePanel({
  novelId,
  chapter,
  novelTitle,
  models,
  selectedModelId,
  onModelChange,
  onGoToWorkbench,
  onApplied,
  onReverted,
  onOpenHistory,
}) {
  const toast = useToast();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [runningAll, setRunningAll] = useState(false);
  const [runningStep, setRunningStep] = useState(null);
  const [intent, setIntent] = useState('');
  const [intentDirty, setIntentDirty] = useState(false);
  const [diff, setDiff] = useState(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [viewMode, setViewMode] = useState('preview'); // preview / merged / sidebyside / highlight
  const [applying, setApplying] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [openSteps, setOpenSteps] = useState({
    step1: true,
    step2: true,
    step3: true,
  });
  const lastSavedIntentRef = useRef('');

  // 拉详情
  useEffect(() => {
    if (!chapter?.id) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await api.enrichment.getDetail(chapter.id);
        if (!cancelled) {
          setDetail(data);
          const initialIntent = data?.enrichment_intent || '';
          setIntent(initialIntent);
          lastSavedIntentRef.current = initialIntent;
          setIntentDirty(false);
        }
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载加料失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chapter?.id, toast]);

  const enabledChatModels = useMemo(
    () => (models || []).filter(
      (m) => (m.capability || 'chat') === 'chat' && m.enabled
    ),
    [models]
  );

  const recognition = detail?.recognition || {};
  const characters = useMemo(
    () => (Array.isArray(recognition.characters) ? recognition.characters : []),
    [recognition]
  );
  const events = useMemo(
    () => (Array.isArray(recognition.events) ? recognition.events : []),
    [recognition]
  );

  const hasSummary = detail?.summary_status === 'done' && detail?.summary;
  const hasRecognition = detail?.recognition_status === 'done';
  const hasRewrite = detail?.rewrite_status === 'done' && detail?.rewrite_text;

  const handleRunAll = async () => {
    if (!selectedModelId) {
      toast.error('请先选择可用的 chat 模型');
      return;
    }
    setRunningAll(true);
    try {
      // 先保存 intent
      if (intentDirty && intent !== (detail?.enrichment_intent || '')) {
        try {
          await api.enrichment.updateDetail(chapter.id, {
            enrichment_intent: intent,
          });
          setIntentDirty(false);
        } catch (err) {
          toast.error(err instanceof ApiError ? err.message : '保存加料需求失败');
        }
      }
      for (const step of ['summary', 'recognition', 'rewrite']) {
        // eslint-disable-next-line no-await-in-loop
        await runSingleStep(step, { silent: true });
      }
      toast.success('一键生成完成');
    } finally {
      setRunningAll(false);
    }
  };

  const runSingleStep = async (step, opts = {}) => {
    if (!chapter?.id) return;
    if (!selectedModelId) {
      if (!opts.silent) toast.error('请先选择可用的 chat 模型');
      return;
    }
    setRunningStep(step);
    const fnMap = {
      summary: api.enrichment.runSummary,
      recognition: api.enrichment.runRecognition,
      rewrite: api.enrichment.runRewrite,
    };
    try {
      const payload = { model_config_id: selectedModelId };
      if (step === 'rewrite') {
        payload.enrichment_intent = intent;
      }
      await fnMap[step](chapter.id, payload);
      const fresh = await api.enrichment.getDetail(chapter.id);
      setDetail(fresh);
      if (!opts.silent) {
        const status = fresh[`${step}_status`];
        if (status === 'done') {
          toast.success(`${STEP_LABELS[step]} 完成`);
        } else if (status === 'failed') {
          toast.error(
            `${STEP_LABELS[step]} 失败: ${fresh[`${step}_error`] || '未知错误'}`
          );
        }
      }
    } catch (err) {
      if (!opts.silent) {
        toast.error(err instanceof ApiError ? err.message : '执行失败');
      }
    } finally {
      setRunningStep(null);
    }
  };

  // 加载 diff
  const handleLoadPreview = useCallback(async () => {
    if (!chapter?.id) return;
    setDiffLoading(true);
    try {
      const data = await api.enrichment.diff(chapter.id);
      setDiff(data);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '加载 diff 失败');
    } finally {
      setDiffLoading(false);
    }
  }, [chapter?.id, toast]);

  useEffect(() => {
    if (!chapter?.id || !hasRewrite || diff || diffLoading) return;
    handleLoadPreview();
  }, [chapter?.id, hasRewrite, diff, diffLoading, handleLoadPreview]);

  const handleApply = async () => {
    if (!chapter?.id) return;
    setApplying(true);
    try {
      const res = await api.enrichment.apply(chapter.id, {
        enrichment_intent: intent,
      });
      toast.success(
        `已应用: 净增 ${(res.added_length - res.removed_length).toLocaleString()} 字`
      );
      const fresh = await api.enrichment.getDetail(chapter.id);
      setDetail(fresh);
      onApplied?.({ chapterId: chapter.id, suggestionId: res.suggestion_id });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '应用失败');
    } finally {
      setApplying(false);
    }
  };

  const handleRevert = async () => {
    if (!chapter?.id) return;
    setReverting(true);
    try {
      const res = await api.enrichment.revert(chapter.id);
      toast.success(
        `已回滚: 章节正文变为 ${res.new_content_length.toLocaleString()} 字`
      );
      const fresh = await api.enrichment.getDetail(chapter.id);
      setDetail(fresh);
      onReverted?.({ chapterId: chapter.id, newAppliedId: res.new_applied_suggestion_id });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '回滚失败');
    } finally {
      setReverting(false);
    }
  };

  // 通用保存
  const updateDetail = async (payload) => {
    if (!chapter?.id) return;
    try {
      const fresh = await api.enrichment.updateDetail(chapter.id, payload);
      setDetail(fresh);
      toast.success('已保存');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '保存失败');
      throw err;
    }
  };

  const toggleStep = (k) => setOpenSteps((s) => ({ ...s, [k]: !s[k] }));

  if (!chapter) {
    return (
      <div className="enrichment-side-panel empty">
        <p>从左侧选择章节, 开始 AI 加料</p>
      </div>
    );
  }

  return (
    <div className="enrichment-side-panel">
      <header className="enrichment-side-panel-head">
        <div className="enrichment-side-panel-title-row">
          <h4>AI 加料工坊</h4>
          {detail?.has_applied && (
            <span className="enrichment-side-panel-applied-pill">
              ✓ 已应用 · {detail?.applied_at ? new Date(detail.applied_at).toLocaleString('zh-CN', { hour12: false }) : ''}
            </span>
          )}
        </div>
        <p className="enrichment-side-panel-sub">
          {novelTitle ? `${novelTitle} · ` : ''}
          第 {chapter.chapter_number} 章 {chapter.title}
        </p>
      </header>

      <div className="enrichment-side-panel-body">
        {loading && !detail ? (
          <div className="library-list-loading">
            <div className="loading-spinner small" />
            <span>载入加料...</span>
          </div>
        ) : (
          <>
            {/* 模型选择 */}
            <div className="enrichment-side-panel-model">
              <label>模型</label>
              <select
                value={selectedModelId || ''}
                onChange={(e) => onModelChange?.(Number(e.target.value) || null)}
                disabled={!!runningStep || runningAll}
              >
                {enabledChatModels.length === 0 ? (
                  <option value="">(无可用模型, 请去系统设置添加)</option>
                ) : (
                  enabledChatModels.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))
                )}
              </select>
              {enabledChatModels.length === 0 && (
                <button
                  type="button"
                  className="enrichment-side-panel-link"
                  onClick={onGoToWorkbench}
                >
                  去添加 →
                </button>
              )}
            </div>

            {/* ===== Step 1: 拆解 ===== */}
            <div className={`enrichment-step-card ${openSteps.step1 ? 'open' : 'closed'}`}>
              <header
                className="enrichment-step-card-head"
                onClick={() => toggleStep('step1')}
              >
                <span className="enrichment-step-num">1</span>
                <span className="enrichment-step-label">拆解 (Context Builder)</span>
                <span className="enrichment-step-status">
                  {hasSummary ? '✓' : '○'}
                </span>
                <span className="enrichment-step-toggle">{openSteps.step1 ? '−' : '+'}</span>
              </header>
              {openSteps.step1 && (
                <div className="enrichment-step-card-body">
                  <div className="enrichment-step-subhead">
                    <span>章节概要</span>
                    <button
                      type="button"
                      className="enrichment-step-rebuild"
                      onClick={() => runSingleStep('summary')}
                      disabled={!selectedModelId || !!runningStep}
                    >
                      {runningStep === 'summary' ? (
                        <span className="loading-spinner small" />
                      ) : (
                        '重新拆解'
                      )}
                    </button>
                  </div>
                  <EditableField
                    value={detail?.summary || ''}
                    onSave={(v) => updateDetail({ summary: v })}
                    multiline
                    rows={4}
                    emptyHint="点击「重新拆解」让 AI 生成, 或直接补充"
                  />

                  <div className="enrichment-step-subhead">
                    <span>场景标签</span>
                    <button
                      type="button"
                      className="enrichment-step-rebuild"
                      onClick={() => runSingleStep('recognition')}
                      disabled={!selectedModelId || !!runningStep}
                    >
                      {runningStep === 'recognition' ? (
                        <span className="loading-spinner small" />
                      ) : (
                        '重新识别'
                      )}
                    </button>
                  </div>
                  <SceneTagField
                    value={detail?.scene_tag || ''}
                    options={SCENE_OPTIONS}
                    onSave={(v) => updateDetail({ scene_tag: v })}
                    disabled={!!runningStep}
                  />

                  <div className="enrichment-step-subhead">
                    <span>登场人物 ({characters.length})</span>
                  </div>
                  <EditableListField
                    items={characters}
                    onSave={(items) =>
                      updateDetail({
                        recognition: { ...recognition, characters: items },
                      })
                    }
                    nameLabel="姓名"
                    descLabel="描述"
                    disabled={!!runningStep}
                  />

                  <div className="enrichment-step-subhead">
                    <span>关键事件 ({events.length})</span>
                  </div>
                  <EditableListField
                    items={events}
                    onSave={(items) =>
                      updateDetail({
                        recognition: { ...recognition, events: items },
                      })
                    }
                    nameLabel="事件"
                    descLabel="说明"
                    disabled={!!runningStep}
                  />

                  {/* Step 1 内嵌 prompt 上下文 */}
                  <ContextPreview
                    chapterTitle={detail?.title || chapter.title}
                    chapterText={detail?.content || ''}
                    summary={detail?.summary || ''}
                    recognition={recognition}
                    sceneTag={detail?.scene_tag || ''}
                    enrichmentIntent={intent}
                    generalRule=""
                    sceneRule=""
                  />
                </div>
              )}
            </div>

            {/* ===== Step 2: 加料需求 ===== */}
            <div className={`enrichment-step-card ${openSteps.step2 ? 'open' : 'closed'}`}>
              <header
                className="enrichment-step-card-head"
                onClick={() => toggleStep('step2')}
              >
                <span className="enrichment-step-num">2</span>
                <span className="enrichment-step-label">加料需求 (Intent)</span>
                <span className="enrichment-step-status">
                  {intent.trim() ? '✎' : '○'}
                </span>
                <span className="enrichment-step-toggle">{openSteps.step2 ? '−' : '+'}</span>
              </header>
              {openSteps.step2 && (
                <div className="enrichment-step-card-body">
                  <p className="enrichment-step-hint">
                    告诉 AI 你想怎么加料. 留空则按通用规则均衡增强.
                  </p>
                  <div className="enrichment-intent-presets">
                    {INTENT_PRESETS.map((p) => (
                      <button
                        key={p.label}
                        type="button"
                        className="enrichment-intent-chip"
                        onClick={() => {
                          setIntent(p.text);
                          setIntentDirty(true);
                        }}
                        title={p.text}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                  <textarea
                    className="enrichment-intent-textarea"
                    rows={5}
                    placeholder="例如: 加入更详细的战斗动作和心理描写 / 把对话改得更口语化 / 在高潮段落增加 200 字..."
                    value={intent}
                    onChange={(e) => {
                      setIntent(e.target.value);
                      setIntentDirty(true);
                    }}
                  />
                  <div className="enrichment-intent-actions">
                    {intentDirty && (
                      <span className="enrichment-intent-hint">已修改</span>
                    )}
                    <button
                      type="button"
                      className="editable-field-btn ghost"
                      onClick={async () => {
                        try {
                          await updateDetail({ enrichment_intent: intent });
                          setIntentDirty(false);
                          lastSavedIntentRef.current = intent;
                        } catch {
                          /* keep dirty */
                        }
                      }}
                      disabled={!intentDirty || !chapter?.id}
                    >
                      仅保存 intent
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* ===== Step 3: 生成与比对 ===== */}
            <div className={`enrichment-step-card ${openSteps.step3 ? 'open' : 'closed'}`}>
              <header
                className="enrichment-step-card-head"
                onClick={() => toggleStep('step3')}
              >
                <span className="enrichment-step-num">3</span>
                <span className="enrichment-step-label">生成与比对</span>
                <span className="enrichment-step-status">
                  {hasRewrite ? '✓' : '○'}
                </span>
                <span className="enrichment-step-toggle">{openSteps.step3 ? '−' : '+'}</span>
              </header>
              {openSteps.step3 && (
                <div className="enrichment-step-card-body">
                  <div className="enrichment-step-subhead">
                    <span>改写正文</span>
                    <button
                      type="button"
                      className="enrichment-step-rebuild"
                      onClick={() => runSingleStep('rewrite')}
                      disabled={!selectedModelId || !!runningStep || runningAll}
                    >
                      {runningStep === 'rewrite' ? (
                        <span className="loading-spinner small" />
                      ) : hasRewrite ? (
                        '重新生成'
                      ) : (
                        '生成改写'
                      )}
                    </button>
                  </div>

                  {!hasRewrite && (
                    <p className="enrichment-side-panel-section-empty">
                      尚未生成改写. 点上方"生成改写"或下方"一键生成"开始.
                    </p>
                  )}

                  {hasRewrite && (
                    <>
                      <div className="enrichment-step-rewrite-meta">
                        <span>
                          原 {(detail.word_count || 0).toLocaleString()} 字 → 改{' '}
                          {(detail.rewrite_text || '').length.toLocaleString()} 字
                        </span>
                      </div>

                      <div className="enrichment-view-mode-tabs">
                        {[
                          { k: 'preview', label: '合并阅读' },
                          { k: 'sidebyside', label: '并排对比' },
                          { k: 'highlight', label: '高亮 diff' },
                        ].map((t) => (
                          <button
                            key={t.k}
                            type="button"
                            className={`enrichment-view-mode-tab ${
                              viewMode === t.k ? 'active' : ''
                            }`}
                            onClick={() => {
                              if (t.k === 'highlight') {
                                if (!diff) handleLoadPreview();
                                setViewMode('highlight');
                              } else {
                                setViewMode(t.k);
                              }
                            }}
                          >
                            {t.label}
                          </button>
                        ))}
                      </div>

                      {viewMode === 'highlight' && (
                        diffLoading || !diff ? (
                          <div className="library-list-loading">
                            <div className="loading-spinner small" />
                            <span>计算 diff...</span>
                          </div>
                        ) : (
                          <HighlightedReader segments={diff.segments} truncated={diff.truncated} />
                        )
                      )}
                      {viewMode === 'preview' && (
                        <MergedReader
                          original={detail.content || ''}
                          rewrite={detail.rewrite_text || ''}
                          diffSegments={diff?.segments || null}
                        />
                      )}
                      {viewMode === 'sidebyside' && (
                        <SideBySideReader
                          original={detail.content || ''}
                          rewrite={detail.rewrite_text || ''}
                          diffSegments={diff?.segments || null}
                        />
                      )}

                      <div className="enrichment-side-panel-apply">
                        {detail?.has_applied ? (
                          <div className="enrichment-side-panel-applied-block">
                            <div className="enrichment-side-panel-applied-tag">
                              ✓ 已应用于原文 · 章节正文已包含本次加料
                            </div>
                            <div className="enrichment-side-panel-apply-actions">
                              <button
                                type="button"
                                className="btn btn-ghost small"
                                onClick={handleRevert}
                                disabled={reverting}
                              >
                                {reverting ? (
                                  <span className="loading-spinner small" />
                                ) : null}
                                回滚
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost small"
                                onClick={onOpenHistory}
                              >
                                查看历史
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-primary block"
                            onClick={handleApply}
                            disabled={applying}
                          >
                            {applying ? (
                              <span className="loading-spinner small" />
                            ) : (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                                <path
                                  d="M5 13l4 4L19 7"
                                  stroke="currentColor"
                                  strokeWidth="2"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                              </svg>
                            )}
                            应用到原文
                          </button>
                        )}
                      </div>
                    </>
                  )}

                  <div className="enrichment-side-panel-actions-row">
                    <button
                      type="button"
                      className="btn btn-primary block"
                      onClick={handleRunAll}
                      disabled={!selectedModelId || runningAll || !!runningStep}
                    >
                      {runningAll ? (
                        <span className="loading-spinner small" />
                      ) : (
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                          <polygon
                            points="5 3 19 12 5 21 5 3"
                            stroke="currentColor"
                            strokeWidth="2"
                          />
                        </svg>
                      )}
                      一键生成 (三步全跑)
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const STEP_LABELS = {
  summary: '内容总结',
  recognition: '人物事件识别',
  rewrite: 'AI 改写',
};
