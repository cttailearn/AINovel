import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';
import { KnowledgeGraphVisualizer } from './KnowledgeGraphVisualizer.jsx';
import { EntityDetailModal } from './EntityDetailModal.jsx';
import { ExtractionProgress } from './ExtractionProgress.jsx';
import { EvidenceReader } from './EvidenceReader.jsx';
import { ConfirmDialog } from './Modal/ConfirmDialog.jsx';

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

function renderAttrs(attrs, max = 4) {
  const entries = Object.entries(attrs || {}).slice(0, max);
  if (entries.length === 0) return null;
  return (
    <ul className="kg-attr-list">
      {entries.map(([k, v]) => (
        <li key={k}>
          <span className="kg-attr-key">{k}</span>
          <span className="kg-attr-val">
            {Array.isArray(v) ? v.join('、') : String(v)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function CharacterCard({ character, index, onClick }) {
  const initial = (character.name || '?').slice(0, 1);
  return (
    <article
      className="character-card"
      onClick={() => onClick?.(character)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onClick?.(character);
      }}
    >
      <div className="character-avatar" aria-hidden>
        {initial}
      </div>
      <div className="character-body">
        <header>
          <h4>{character.name}</h4>
          <span className="character-role">{character.entity_id}</span>
        </header>
        {renderAttrs(character.attributes)}
      </div>
      <span className="character-index">#{index + 1}</span>
    </article>
  );
}

function EventCard({ event, index, onClick }) {
  return (
    <article
      className="event-card"
      onClick={() => onClick?.(event)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onClick?.(event);
      }}
    >
      <div className="event-head">
        <h4>{event.name}</h4>
        <span className="event-entity-id">{event.entity_id}</span>
      </div>
      {renderAttrs(event.attributes)}
      <span className="event-index">#{index + 1}</span>
    </article>
  );
}

function RelationRow({ relation, kind, entityMap, onClick }) {
  const sourceName = entityMap[relation.source] || relation.source;
  const targetName = entityMap[relation.target] || relation.target;
  const extra =
    relation.role || relation.action
      ? `（${[relation.role, relation.action].filter(Boolean).join(' · ')}）`
      : '';
  return (
    <li
      className={`kg-rel-row kg-rel-${kind}`}
      onClick={() => onClick?.(relation)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onClick?.(relation);
      }}
    >
      <span className="kg-rel-side">{sourceName}</span>
      <span className="kg-rel-tag">{relation.relation}</span>
      <span className="kg-rel-side">{targetName}</span>
      {extra && <span className="kg-rel-extra">{extra}</span>}
    </li>
  );
}

const TABS = [
  { key: 'graph', label: '图谱视图' },
  { key: 'characters', label: '人物' },
  { key: 'events', label: '事件' },
  { key: 'relations', label: '关系' },
  { key: 'validation', label: '校验' },
];

function ValidationPanel({ validation, useV2 }) {
  if (!useV2) {
    return (
      <div className="kg-validation-empty">
        <p>未启用 v2 校验</p>
        <span>勾选工具栏「v2 多 Agent 校验」并构建,即可看到抽取质量报告</span>
      </div>
    );
  }
  if (!validation) {
    return (
      <div className="kg-validation-empty">
        <p>尚无校验报告</p>
        <span>点击「构建知识图谱」后, 校验 Agent 会自动生成报告</span>
      </div>
    );
  }
  const issues = validation.issues || [];
  const dedup = validation.dedup_log || [];
  const cov = validation.coverage || {};
  const byCode = issues.reduce((acc, it) => {
    acc[it.code] = (acc[it.code] || 0) + 1;
    return acc;
  }, {});
  const errors = issues.filter((i) => i.severity === 'error').length;
  const warns = issues.filter((i) => i.severity === 'warn').length;
  const perEvent = cov.per_event_participant_count || {};
  const orphanEvents = cov.events_without_participant || [];
  return (
    <div className="kg-validation">
      <div className="kg-validation-summary">
        <div>
          <span className="summary-label">问题</span>
          <strong>{issues.length}</strong>
          <span className="summary-sub">
            (错误 {errors} · 警告 {warns})
          </span>
        </div>
        <div>
          <span className="summary-label">同义合并</span>
          <strong>{dedup.length}</strong>
        </div>
        <div>
          <span className="summary-label">参与缺失事件</span>
          <strong>{orphanEvents.length}</strong>
        </div>
        <div>
          <span className="summary-label">事件总数</span>
          <strong>{cov.events ?? '-'}</strong>
        </div>
      </div>

      {Object.keys(byCode).length > 0 && (
        <section className="kg-validation-section">
          <h4>问题分类</h4>
          <ul className="kg-validation-codes">
            {Object.entries(byCode)
              .sort((a, b) => b[1] - a[1])
              .map(([code, count]) => (
                <li key={code}>
                  <span className="kg-validation-code">{code}</span>
                  <span className="kg-validation-count">{count}</span>
                </li>
              ))}
          </ul>
        </section>
      )}

      {issues.length > 0 && (
        <section className="kg-validation-section">
          <h4>问题详情</h4>
          <ul className="kg-validation-list">
            {issues.map((it, i) => (
              <li
                key={i}
                className={`kg-validation-item kg-validation-${it.severity}`}
              >
                <span className={`kg-validation-pill kg-validation-pill-${it.severity}`}>
                  {it.severity}
                </span>
                <span className="kg-validation-code">{it.code}</span>
                <span className="kg-validation-msg">{it.message}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {dedup.length > 0 && (
        <section className="kg-validation-section">
          <h4>同义合并记录</h4>
          <ul className="kg-validation-dedup">
            {dedup.map((d, i) => (
              <li key={i}>
                <strong>{d.kept}</strong> ← {d.names?.join(' / ')}
                <span className="kg-validation-sub">
                  合并自 {d.merged_from?.join(', ')}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {perEvent && Object.keys(perEvent).length > 0 && (
        <section className="kg-validation-section">
          <h4>每事件参与数</h4>
          <ul className="kg-validation-coverage">
            {Object.entries(perEvent).map(([eid, cnt]) => (
              <li
                key={eid}
                className={cnt === 0 ? 'kg-validation-coverage-zero' : ''}
              >
                <span>{eid}</span>
                <strong>{cnt}</strong>
              </li>
            ))}
          </ul>
        </section>
      )}

      {cov.completeness && (
        <section className="kg-validation-section">
          <h4>覆盖度核查 (LLM)</h4>
          <div className="kg-validation-completeness">
            <div>
              <span className="summary-label">缺失人物</span>
              <strong>{(cov.completeness.missing_characters || []).length}</strong>
            </div>
            <div>
              <span className="summary-label">缺失事件</span>
              <strong>{(cov.completeness.missing_events || []).length}</strong>
            </div>
            <div>
              <span className="summary-label">缺失参与</span>
              <strong>{(cov.completeness.missing_participations || []).length}</strong>
            </div>
          </div>
          {(cov.completeness.missing_characters || []).length > 0 && (
            <details>
              <summary>查看缺失人物</summary>
              <ul>
                {cov.completeness.missing_characters.map((c, i) => (
                  <li key={i}>
                    <strong>{c.name}</strong>
                    <span className="kg-validation-evidence">
                      {c.evidence}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {(cov.completeness.missing_events || []).length > 0 && (
            <details>
              <summary>查看缺失事件</summary>
              <ul>
                {cov.completeness.missing_events.map((e, i) => (
                  <li key={i}>
                    <strong>{e.name}</strong>
                    <span className="kg-validation-evidence">
                      {e.evidence}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
    </div>
  );
}

export function KnowledgeGraphPanel({ novelId, models, novelTitle, onExtracted }) {
  const toast = useToast();
  const [data, setData] = useState({
    characters: [],
    events: [],
    character_event_relations: [],
    character_relations: [],
    event_relations: [],
  });
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [modelConfigId, setModelConfigId] = useState('');
  const [chunkSize, setChunkSize] = useState(8000);
  const [maxConcurrency, setMaxConcurrency] = useState(3);
  const [lastModel, setLastModel] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [activeTab, setActiveTab] = useState('graph');
  const [relSubTab, setRelSubTab] = useState('participations');

  // v2 (multi-agent) toggles
  const [useV2, setUseV2] = useState(false);
  const [runCompleteness, setRunCompleteness] = useState(false);
  const [validation, setValidation] = useState(null);

  // Streaming / live updates
  const [progress, setProgress] = useState(null);
  const [phaseStats, setPhaseStats] = useState({});
  const [extractError, setExtractError] = useState(null);
  const [extractStatus, setExtractStatus] = useState('idle'); // idle|running|done|error
  const abortRef = useRef(null);
  // Hold a snapshot of the live data while the extraction is running
  // (before the final result is stored in the DB).
  const [liveData, setLiveData] = useState(null);

  // Entity detail modal
  const [detailSelection, setDetailSelection] = useState(null);

  // 原文引用阅读器 + 二次确认
  const [readerState, setReaderState] = useState(null); // { evidenceList, jumpTo, anchor }
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmReExtract, setConfirmReExtract] = useState(false);
  const [managing, setManaging] = useState(false); // 重新提取/删除进行中

  const enabledModels = models.filter((m) => m.enabled);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const kg = await api.novels.listCharacters(novelId);
        if (cancelled) return;
        setData({
          characters: kg.characters || [],
          events: kg.events || [],
          character_event_relations: kg.character_event_relations || [],
          character_relations: kg.character_relations || [],
          event_relations: kg.event_relations || [],
        });
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载知识图谱失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [novelId, toast]);

  useEffect(() => () => {
    abortRef.current?.abort?.();
  }, []);

  const handleExtract = async () => {
    if (enabledModels.length === 0) {
      toast.error('请先在「系统设置」中启用模型');
      return;
    }
    // Reset state
    setExtractStatus('running');
    setProgress({ percent: 0, message: '准备开始…' });
    setPhaseStats({});
    setExtractError(null);
    setValidation(null);
    setLiveData({
      characters: [],
      events: [],
      character_event_relations: [],
      character_relations: [],
      event_relations: [],
    });

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setExtracting(true);

    try {
      const requestPayload = {
        model_config_id: modelConfigId ? Number(modelConfigId) : null,
        chunk_size: Number(chunkSize),
        max_concurrency: Number(maxConcurrency),
        ...(useV2
          ? { run_validator: true, run_llm_dedup: true, run_llm_completeness: runCompleteness }
          : {}),
      };
      const streamCall = useV2
        ? api.novels.extractCharactersStreamV2
        : api.novels.extractCharactersStream;

      await streamCall(
        novelId,
        requestPayload,
        {
          signal: controller.signal,
          onEvent: ({ event, data }) => {
            if (event === 'progress') {
              setProgress(data);
            } else if (event === 'validation') {
              // v2-only event: validator report after the run completes.
              setValidation(data);
            } else if (event === 'partial') {
              const key = Object.keys(data || {})[0];
              if (!key) return;
              const items = data[key] || [];
              setLiveData((prev) => {
                const next = { ...(prev || {}) };
                if (key === 'characters') next.characters = items;
                else if (key === 'events') next.events = items;
                else if (key === 'participations') next.character_event_relations = items;
                else if (key === 'char_relations') next.character_relations = items;
                else if (key === 'event_relations') next.event_relations = items;
                return next;
              });
              // Also surface running count in phase stats during partials
              // (so the progress UI shows growing numbers as work proceeds).
              if (
                data[key]?.length !== undefined &&
                ['characters', 'events'].includes(key)
              ) {
                setPhaseStats((prev) => ({
                  ...prev,
                  [key]: { count: data[key].length, partial: true },
                }));
              }
            } else if (event === 'done') {
              // Final result includes stored entities with `entity_id`.
              const result = data || {};
              if (result.validation) setValidation(result.validation);
              setData({
                characters: result.characters || [],
                events: result.events || [],
                character_event_relations: result.character_event_relations || [],
                character_relations: result.character_relations || [],
                event_relations: result.event_relations || [],
              });
              const stats = result.stats || {};
              setPhaseStats({
                characters: { count: stats.characters || 0 },
                events: { count: stats.events || 0 },
                participations: { count: stats.participations || 0 },
                char_relations: { count: stats.character_relations || 0 },
                event_relations: { count: stats.event_relations || 0 },
              });
              setLastModel(result.model || null);
              setUpdatedAt(new Date().toLocaleTimeString());
              setProgress({ percent: 100, message: '构建完成' });
              setExtractStatus('done');
              toast.success(
                `抽取完成：${stats.characters || 0} 位人物、${stats.events || 0} 个事件`
              );
              setLiveData(null);
              onExtracted?.();
            } else if (event === 'error') {
              setExtractError(typeof data === 'string' ? data : '抽取失败');
              setExtractStatus('error');
              toast.error(typeof data === 'string' ? data : '知识图谱构建失败');
            }
          },
        }
      );
    } catch (err) {
      if (err && err.name === 'AbortError') {
        setExtractStatus('idle');
        setProgress(null);
        toast.info('已取消');
        return;
      }
      const message = err instanceof ApiError ? err.message : '知识图谱构建失败';
      setExtractError(message);
      setExtractStatus('error');
      toast.error(message);
    } finally {
      setExtracting(false);
      abortRef.current = null;
    }
  };

  const handleCancel = () => {
    abortRef.current?.abort();
  };

  // ---- KG 管理: 删除 / 重新提取 ---------------------------------------

  const handleDelete = async () => {
    setConfirmDelete(false);
    if (!isEmpty) {
      // 有数据才走删除, 空 KG 直接清理本地 state
    }
    setManaging(true);
    try {
      const result = await api.novels.deleteKnowledgeGraph(novelId);
      const d = result?.deleted || {};
      setData({
        characters: [],
        events: [],
        character_event_relations: [],
        character_relations: [],
        event_relations: [],
      });
      setValidation(null);
      setLiveData(null);
      setDetailSelection(null);
      setExtractStatus('idle');
      setProgress(null);
      setLastModel(null);
      setUpdatedAt(null);
      toast.success(
        `已删除: ${d.characters || 0} 人物 / ${d.events || 0} 事件 / ${
          (d.participations || 0) +
          (d.character_relations || 0) +
          (d.event_relations || 0)
        } 关系`
      );
      onExtracted?.();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : '删除知识图谱失败';
      toast.error(message);
    } finally {
      setManaging(false);
    }
  };

  const handleReExtract = async () => {
    setConfirmReExtract(false);
    if (enabledModels.length === 0) {
      toast.error('请先在「系统设置」中启用模型');
      return;
    }
    setManaging(true);
    setExtractStatus('running');
    setProgress({ percent: 0, message: '准备重新抽取…' });
    setPhaseStats({});
    setExtractError(null);
    setValidation(null);
    setLiveData({
      characters: [],
      events: [],
      character_event_relations: [],
      character_relations: [],
      event_relations: [],
    });

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const requestPayload = {
        model_config_id: modelConfigId ? Number(modelConfigId) : null,
        chunk_size: Number(chunkSize),
        max_concurrency: Number(maxConcurrency),
        run_validator: useV2,
        run_llm_dedup: useV2,
        run_llm_completeness: useV2 ? runCompleteness : false,
      };
      // re-extract 走的是 /re-extract 端点, 但前端用 v2 流式展现进度
      // 先以 v2 流式订阅 partial + validation + done, 失败时回退到 POST 一次性调用
      try {
        await api.novels.extractCharactersStreamV2(
          novelId,
          requestPayload,
          {
            signal: controller.signal,
            onEvent: ({ event, data }) => {
              if (event === 'progress') setProgress(data);
              else if (event === 'partial') {
                const key = Object.keys(data || {})[0];
                if (!key) return;
                const items = data[key] || [];
                setLiveData((prev) => {
                  const next = { ...(prev || {}) };
                  if (key === 'characters') next.characters = items;
                  else if (key === 'events') next.events = items;
                  else if (key === 'participations') next.character_event_relations = items;
                  else if (key === 'char_relations') next.character_relations = items;
                  else if (key === 'event_relations') next.event_relations = items;
                  return next;
                });
              } else if (event === 'done') {
                const result = data || {};
                if (result.validation) setValidation(result.validation);
                setData({
                  characters: result.characters || [],
                  events: result.events || [],
                  character_event_relations: result.character_event_relations || [],
                  character_relations: result.character_relations || [],
                  event_relations: result.event_relations || [],
                });
                setLastModel(result.model || null);
                setUpdatedAt(new Date().toLocaleTimeString());
                setProgress({ percent: 100, message: '重新抽取完成' });
                setExtractStatus('done');
                setLiveData(null);
                toast.success('重新抽取完成');
                onExtracted?.();
              } else if (event === 'error') {
                setExtractError(typeof data === 'string' ? data : '重新抽取失败');
                setExtractStatus('error');
                toast.error(typeof data === 'string' ? data : '重新抽取失败');
              }
            },
          }
        );
      } catch (streamErr) {
        // 流式不可用时 (例如旧版后端未实现 v2 stream), 回退到 POST 一次性调用
        const result = await api.novels.reExtractKnowledgeGraph(
          novelId,
          requestPayload,
          { signal: controller.signal }
        );
        if (result.validation) setValidation(result.validation);
        setData({
          characters: result.characters || [],
          events: result.events || [],
          character_event_relations: result.character_event_relations || [],
          character_relations: result.character_relations || [],
          event_relations: result.event_relations || [],
        });
        setLastModel(result.model || null);
        setUpdatedAt(new Date().toLocaleTimeString());
        setExtractStatus('done');
        setProgress({ percent: 100, message: '重新抽取完成' });
        setLiveData(null);
        toast.success('重新抽取完成');
        onExtracted?.();
      }
    } catch (err) {
      if (err && err.name === 'AbortError') {
        setExtractStatus('idle');
        setProgress(null);
        toast.info('已取消');
        return;
      }
      const message = err instanceof ApiError ? err.message : '重新抽取失败';
      setExtractError(message);
      setExtractStatus('error');
      toast.error(message);
    } finally {
      setManaging(false);
      setExtracting(false);
      abortRef.current = null;
    }
  };

  // During streaming we render `liveData` (so the user sees entities
  // appear as they're extracted). After completion we render `data`.
  const renderData = useMemo(() => {
    if (extractStatus === 'running' && liveData) {
      // Merge in any data already persisted from previous runs.
      return {
        characters: liveData.characters?.length ? liveData.characters : data.characters,
        events: liveData.events?.length ? liveData.events : data.events,
        character_event_relations: liveData.character_event_relations?.length
          ? liveData.character_event_relations
          : data.character_event_relations,
        character_relations: liveData.character_relations?.length
          ? liveData.character_relations
          : data.character_relations,
        event_relations: liveData.event_relations?.length
          ? liveData.event_relations
          : data.event_relations,
      };
    }
    return data;
  }, [extractStatus, liveData, data]);

  const handleSelectCharacter = useCallback((c) => {
    setDetailSelection({ type: 'character', entity: c });
  }, []);
  const handleSelectEvent = useCallback((e) => {
    setDetailSelection({ type: 'event', entity: e });
  }, []);
  const handleSelectRelation = useCallback((r) => {
    setDetailSelection({ type: 'relation', relation: r });
  }, []);
  const handleSelectGraphNode = useCallback((node) => {
    if (!node) return;
    if (node.type === 'character') {
      // Try to use the latest data version of the character
      const fresh = data.characters.find((c) => c.entity_id === node.entity_id);
      setDetailSelection({ type: 'character', entity: fresh || node });
    } else if (node.type === 'event') {
      const fresh = data.events.find((e) => e.entity_id === node.entity_id);
      setDetailSelection({ type: 'event', entity: fresh || node });
    }
  }, [data.characters, data.events]);

  const entityMap = useMemo(() => {
    const m = {};
    renderData.characters.forEach((c) => {
      if (c.entity_id) m[c.entity_id] = c.name;
    });
    renderData.events.forEach((e) => {
      if (e.entity_id) m[e.entity_id] = e.name;
    });
    return m;
  }, [renderData.characters, renderData.events]);

  const counts = useMemo(
    () => ({
      characters: renderData.characters.length,
      events: renderData.events.length,
      participations: renderData.character_event_relations.length,
      character_relations: renderData.character_relations.length,
      event_relations: renderData.event_relations.length,
    }),
    [renderData]
  );

  const isEmpty =
    counts.characters === 0 &&
    counts.events === 0 &&
    counts.participations === 0 &&
    counts.character_relations === 0 &&
    counts.event_relations === 0;

  return (
    <div className="character-panel kg-panel">
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
          <label>分块大小</label>
          <select
            value={chunkSize}
            onChange={(e) => setChunkSize(Number(e.target.value))}
            disabled={extracting}
          >
            <option value={4000}>4000 字</option>
            <option value={8000}>8000 字</option>
            <option value={16000}>16000 字</option>
            <option value={32000}>32000 字</option>
          </select>
        </div>
        <div className="toolbar-field small">
          <label>并发数</label>
          <input
            type="number"
            min={1}
            max={10}
            value={maxConcurrency}
            onChange={(e) => setMaxConcurrency(Number(e.target.value) || 1)}
            disabled={extracting}
          />
        </div>
        <div className="toolbar-field small toolbar-toggle">
          <label>
            <input
              type="checkbox"
              checked={useV2}
              onChange={(e) => setUseV2(e.target.checked)}
              disabled={extracting}
            />
            <span>v2 多 Agent 校验</span>
          </label>
        </div>
        {useV2 && (
          <div className="toolbar-field small toolbar-toggle">
            <label>
              <input
                type="checkbox"
                checked={runCompleteness}
                onChange={(e) => setRunCompleteness(e.target.checked)}
                disabled={extracting}
              />
              <span>覆盖度核查 (LLM)</span>
            </label>
          </div>
        )}
        <button
          type="button"
          className="extract-btn"
          onClick={handleExtract}
          disabled={extracting || enabledModels.length === 0}
        >
          {extracting ? (
            <>
              <span className="loading-spinner small"></span>
              构建中...
            </>
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
                <circle cx="4" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
                <circle cx="20" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
                <circle cx="4" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
                <circle cx="20" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
                <path d="M6 6l4 4M18 6l-4 4M6 18l4-4M18 18l-4-4" stroke="currentColor" strokeWidth="1.5" />
              </svg>
              构建知识图谱
            </>
          )}
        </button>

        {/* KG 管理: 重新提取 / 删除 */}
        <div className="kg-manage-group">
          <button
            type="button"
            className="kg-manage-btn"
            onClick={() => setConfirmReExtract(true)}
            disabled={
              extracting || managing || enabledModels.length === 0 || isEmpty
            }
            title={isEmpty ? '当前没有可重新提取的知识图谱' : '删除当前图谱后重新抽取'}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="2">
              <path
                d="M23 4v6h-6M1 20v-6h6"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            重新提取
          </button>
          <button
            type="button"
            className="kg-manage-btn is-danger"
            onClick={() => setConfirmDelete(true)}
            disabled={extracting || managing || isEmpty}
            title="清空当前图谱（不重新抽取）"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="2">
              <path
                d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6M10 11v6M14 11v6"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            删除图谱
          </button>
        </div>
      </div>

      <div className="character-summary kg-summary">
        <div>
          <span className="summary-label">人物</span>
          <strong>{counts.characters}</strong>
        </div>
        <div>
          <span className="summary-label">事件</span>
          <strong>{counts.events}</strong>
        </div>
        <div>
          <span className="summary-label">参与</span>
          <strong>{counts.participations}</strong>
        </div>
        <div>
          <span className="summary-label">人物关系</span>
          <strong>{counts.character_relations}</strong>
        </div>
        <div>
          <span className="summary-label">事件关系</span>
          <strong>{counts.event_relations}</strong>
        </div>
        {lastModel && (
          <div className="summary-sub">
            <span>使用模型：</span>
            <strong>{lastModel}</strong>
          </div>
        )}
        {updatedAt && <div className="summary-sub">更新于 {updatedAt}</div>}
      </div>

      <ExtractionProgress
        status={extractStatus}
        progress={progress}
        phaseStats={phaseStats}
        error={extractError}
        onCancel={handleCancel}
      />

      <div className="kg-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`kg-tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
            {tab.key === 'graph' && (
              <span className="kg-tab-count">
                {counts.characters + counts.events}
              </span>
            )}
            {tab.key === 'characters' && <span className="kg-tab-count">{counts.characters}</span>}
            {tab.key === 'events' && <span className="kg-tab-count">{counts.events}</span>}
            {tab.key === 'relations' && (
              <span className="kg-tab-count">
                {counts.participations + counts.character_relations + counts.event_relations}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading-block">
          <div className="loading-spinner large"></div>
          <p>加载知识图谱...</p>
        </div>
      ) : activeTab === 'graph' ? (
        <div className="kg-graph-container">
          {isEmpty ? (
            <div className="character-empty">
              <svg width="56" height="56" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
                <circle cx="4" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
                <circle cx="20" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
                <circle cx="4" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
                <circle cx="20" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
                <path d="M6 6l4 4M18 6l-4 4M6 18l4-4M18 18l-4-4" stroke="currentColor" strokeWidth="1.5" />
              </svg>
              <p>「{novelTitle}」暂无知识图谱</p>
              <span>点击「构建知识图谱」让 AI 抽取人物、事件与关系</span>
            </div>
          ) : (
            <KnowledgeGraphVisualizer
              data={renderData}
              onSelectNode={handleSelectGraphNode}
              onSelectEdge={handleSelectRelation}
              height={520}
            />
          )}
        </div>
      ) : isEmpty ? (
        <div className="character-empty">
          <svg width="56" height="56" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
            <circle cx="4" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
            <circle cx="20" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
            <circle cx="4" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
            <circle cx="20" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
            <path d="M6 6l4 4M18 6l-4 4M6 18l4-4M18 18l-4-4" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <p>「{novelTitle}」暂无知识图谱</p>
          <span>点击「构建知识图谱」让 AI 抽取人物、事件与关系</span>
        </div>
      ) : activeTab === 'characters' ? (
        <div className="character-grid">
          {renderData.characters.map((c, i) => (
            <CharacterCard
              key={c.entity_id || c.id || c.name}
              character={c}
              index={i}
              onClick={handleSelectCharacter}
            />
          ))}
        </div>
      ) : activeTab === 'events' ? (
        <div className="event-grid">
          {renderData.events.map((e, i) => (
            <EventCard
              key={e.entity_id || e.id || e.name}
              event={e}
              index={i}
              onClick={handleSelectEvent}
            />
          ))}
        </div>
      ) : activeTab === 'relations' ? (
        <div className="kg-rel-block">
          <div className="kg-rel-subtabs">
            <button
              type="button"
              className={`kg-rel-subtab ${relSubTab === 'participations' ? 'active' : ''}`}
              onClick={() => setRelSubTab('participations')}
            >
              人物 → 事件
              <span className="kg-tab-count">{counts.participations}</span>
            </button>
            <button
              type="button"
              className={`kg-rel-subtab ${relSubTab === 'char_char' ? 'active' : ''}`}
              onClick={() => setRelSubTab('char_char')}
            >
              人物 ↔ 人物
              <span className="kg-tab-count">{counts.character_relations}</span>
            </button>
            <button
              type="button"
              className={`kg-rel-subtab ${relSubTab === 'event_event' ? 'active' : ''}`}
              onClick={() => setRelSubTab('event_event')}
            >
              事件 → 事件
              <span className="kg-tab-count">{counts.event_relations}</span>
            </button>
          </div>
          <ul className="kg-rel-list">
            {relSubTab === 'participations' &&
              renderData.character_event_relations.map((r, i) => (
                <RelationRow
                  key={`p-${i}`}
                  relation={r}
                  kind="ce"
                  entityMap={entityMap}
                  onClick={handleSelectRelation}
                />
              ))}
            {relSubTab === 'char_char' &&
              renderData.character_relations.map((r, i) => (
                <RelationRow
                  key={`cc-${i}`}
                  relation={r}
                  kind="cc"
                  entityMap={entityMap}
                  onClick={handleSelectRelation}
                />
              ))}
            {relSubTab === 'event_event' &&
              renderData.event_relations.map((r, i) => (
                <RelationRow
                  key={`ee-${i}`}
                  relation={r}
                  kind="ee"
                  entityMap={entityMap}
                  onClick={handleSelectRelation}
                />
              ))}
            {relSubTab === 'participations' && renderData.character_event_relations.length === 0 && (
              <li className="kg-rel-empty">暂无人物参与事件的关系</li>
            )}
            {relSubTab === 'char_char' && renderData.character_relations.length === 0 && (
              <li className="kg-rel-empty">暂无人物间长期关系</li>
            )}
            {relSubTab === 'event_event' && renderData.event_relations.length === 0 && (
              <li className="kg-rel-empty">暂无事件间关系</li>
            )}
          </ul>
        </div>
      ) : activeTab === 'validation' ? (
        <ValidationPanel validation={validation} useV2={useV2} />
      ) : null}

      <EntityDetailModal
        open={!!detailSelection}
        onClose={() => setDetailSelection(null)}
        data={data}
        selection={detailSelection}
        onSelectNode={(sel) => setDetailSelection(sel)}
        onJumpEvidence={(state) => setReaderState(state)}
      />

      <EvidenceReader
        open={!!readerState}
        onClose={() => setReaderState(null)}
        novelId={novelId}
        novelTitle={novelTitle}
        evidenceList={readerState?.evidenceList}
        jumpTo={readerState?.jumpTo}
        onJumpConsumed={() => {
          /* 触发后清掉 jumpTo, 避免 activeIdx 重复设置 */
        }}
        chunkSize={Math.max(Number(chunkSize) || 8000, 8000)}
      />

      <ConfirmDialog
        open={confirmReExtract}
        title="重新提取知识图谱"
        message="将清空当前图谱, 然后重新走一遍抽取流程. 旧的人物/事件/关系将全部丢失 (不可恢复), 请确认无误后继续."
        confirmText="开始重新提取"
        danger={false}
        onConfirm={handleReExtract}
        onCancel={() => setConfirmReExtract(false)}
      />

      <ConfirmDialog
        open={confirmDelete}
        title="删除知识图谱"
        message="将清空当前作品的人物、事件与全部关系. 该操作不可撤销, 如需重建请使用「重新提取」."
        confirmText="确认删除"
        cancelText="取消"
        danger={true}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
