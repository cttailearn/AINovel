// 三选一: Tab 形式的版本切换
// 点击 tab 切换预览 (不切换选中), 点 "选此版本" 才真正选中
// UX-#14: 5 维评分用雷达图展示
import { useEffect, useState } from 'react';
import { ScoreRadar } from './ScoreRadar.jsx';

function ScoreRing({ value, compact = false }) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return (
      <span
        className={`creation-score-ring ${compact ? 'compact' : ''} muted`}
        title="Critic 综合评分"
      >
        —
      </span>
    );
  }
  let tone = 'low';
  if (value >= 8) tone = 'high';
  else if (value >= 6) tone = 'mid';
  return (
    <span
      className={`creation-score-ring ${compact ? 'compact' : ''} tone-${tone}`}
      title="Critic 综合评分"
    >
      {value.toFixed(1)}
    </span>
  );
}

function CriticReport({ report }) {
  if (!report || typeof report !== 'object') return null;
  const scores = report.scores || {};
  return (
    <div className="creation-critic-report">
      {Object.keys(scores).length > 0 && (
        <div className="creation-critic-scores">
          {Object.entries(scores).map(([k, v]) => (
            <div className="creation-critic-score" key={k}>
              <span className="muted small">{k}</span>
              <span>{typeof v === 'number' ? v.toFixed(1) : '—'}</span>
            </div>
          ))}
        </div>
      )}
      {Array.isArray(report.strengths) && report.strengths.length > 0 && (
        <div className="creation-critic-list">
          <h5>亮点</h5>
          <ul>{report.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </div>
      )}
      {Array.isArray(report.issues) && report.issues.length > 0 && (
        <div className="creation-critic-list">
          <h5>问题</h5>
          <ul>{report.issues.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </div>
      )}
      {Array.isArray(report.modifications) && report.modifications.length > 0 && (
        <div className="creation-critic-list">
          <h5>修改建议</h5>
          <ul>{report.modifications.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export function VariantTabs({
  variants,
  selectedId,
  onSelect,
  onEdit,
  onConfirm,
  disabled = false,
}) {
  const [activeIdx, setActiveIdx] = useState(0);

  // 默认打开用户已选中的版本 (章节详情刚加载时)
  useEffect(() => {
    if (!variants || variants.length === 0) return;
    if (selectedId) {
      const idx = variants.findIndex((v) => v.id === selectedId);
      if (idx >= 0) setActiveIdx(idx);
    }
  }, [selectedId, variants]);

  if (!variants || variants.length === 0) {
    return <p className="muted small">暂无候选章节</p>;
  }

  const safeIdx = Math.min(activeIdx, variants.length - 1);
  const active = variants[safeIdx];
  const isSelected = selectedId === active.id;
  const report = active.critic_report || {};
  const focusLine = (active.planner_direction || '').split('\n')[0] || '';
  const charCount = (active.content || '').length;

  return (
    <div className="creation-variant-tabs">
      {/* 顶部 Tab 栏 */}
      <div className="creation-variant-tabs-bar" role="tablist">
        {variants.map((v, i) => {
          const isActive = i === safeIdx;
          const isSel = selectedId === v.id;
          const s = v.score ?? v.critic_report?.overall ?? null;
          const focusShort =
            v.focus_summary ||
            (v.planner_direction || '').split('\n')[0]?.slice(0, 14) ||
            '—';
          return (
            <button
              key={v.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={
                'creation-variant-tab'
                + (isActive ? ' active' : '')
                + (isSel ? ' selected' : '')
              }
              onClick={() => setActiveIdx(i)}
              title={`候选 ${i + 1} · ${v.focus_summary || focusLine || '—'}`}
            >
              <span className="creation-variant-tab-num">候选 {i + 1}</span>
              <span className="creation-variant-tab-focus">{focusShort}</span>
              <ScoreRing value={s} compact />
              {isSel && (
                <span
                  className="creation-variant-tab-check"
                  aria-label="当前已选"
                >
                  ✓
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab 内容区 */}
      <div className="creation-variant-tab-panel" role="tabpanel">
        <div className="creation-variant-tab-panel-head">
          <h4>{active.focus_summary || focusLine || '—'}</h4>
          <span className="muted small">
            候选 {active.variant_index + 1} · {charCount} 字
          </span>
        </div>
        <pre className="creation-variant-tab-content">
          {active.content || '(空)'}
        </pre>
        {report && Object.keys(report).length > 0 && (
          <div className="creation-variant-critic">
            {/* UX-#14: 5 维评分雷达图 */}
            {report.scores && Object.keys(report.scores).length > 0 && (
              <div className="creation-variant-critic-radar">
                <ScoreRadar scores={report.scores} size={200} />
              </div>
            )}
            <CriticReport report={report} />
          </div>
        )}
      </div>

      {/* 操作区 */}
      <div className="creation-variant-tabs-actions">
        {isSelected ? (
          <>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => onEdit(active)}
              disabled={disabled}
              title="进入编辑器微调"
            >
              ✎ 编辑
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => onConfirm(active)}
              disabled={disabled}
              title="确认本章, 内容入图谱"
            >
              确认本章 →
            </button>
          </>
        ) : (
          <>
            <span className="creation-variant-tabs-hint muted small">
              点击下方按钮将此版本设为「已选」
            </span>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => onSelect(active.id)}
              disabled={disabled}
            >
              选此版本 (候选 {active.variant_index + 1})
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// 保留旧名导出以便兼容
export { VariantTabs as VariantCards };
