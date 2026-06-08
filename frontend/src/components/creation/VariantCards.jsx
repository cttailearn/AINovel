// 三选一卡片: 展示 Planner 方向 + Writer 候选 + Critic 评分
import { useState } from 'react';

function ScoreRing({ value }) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return <span className="creation-score-ring muted">—</span>;
  }
  let tone = 'low';
  if (value >= 8) tone = 'high';
  else if (value >= 6) tone = 'mid';
  return (
    <span className={`creation-score-ring tone-${tone}`} title="Critic 综合评分">
      {value.toFixed(1)}
    </span>
  );
}

function CriticReport({ report }) {
  if (!report || typeof report !== 'object') return null;
  const scores = report.scores || {};
  return (
    <div className="creation-critic-report">
      <div className="creation-critic-scores">
        {Object.entries(scores).map(([k, v]) => (
          <div className="creation-critic-score" key={k}>
            <span className="muted small">{k}</span>
            <span>{typeof v === 'number' ? v.toFixed(1) : '—'}</span>
          </div>
        ))}
      </div>
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

export function VariantCards({
  variants,
  selectedId,
  onSelect,
  onEdit,
  onConfirm,
  disabled = false,
}) {
  const [expanded, setExpanded] = useState({});

  if (!variants || variants.length === 0) {
    return <p className="muted small">暂无候选章节</p>;
  }
  return (
    <div className="creation-variant-grid">
      {variants.map((v) => {
        const isSel = selectedId === v.id;
        const isExpanded = expanded[v.id] ?? false;
        const report = v.critic_report || {};
        const score = v.score ?? report.overall ?? null;
        const content = v.content || '';
        const preview = content.slice(0, 200) + (content.length > 200 ? '…' : '');
        return (
          <div
            key={v.id}
            className={`creation-variant-card ${isSel ? 'selected' : ''}`}
          >
            <div className="creation-variant-card-head">
              <div className="creation-variant-card-title">
                <span className="creation-variant-badge">候选 {v.variant_index + 1}</span>
                <span className="muted small">
                  {v.focus_summary || (v.planner_direction || '').split('\n')[0].slice(0, 60)}
                </span>
              </div>
              <ScoreRing value={score} />
            </div>
            <pre className="creation-variant-preview">
              {isExpanded ? content : preview}
            </pre>
            <div className="creation-variant-card-meta muted small">
              {(content || '').length} 字
              {v.planner_direction ? ` · ${(v.planner_direction || '').split('\n')[0]}` : ''}
            </div>
            {isExpanded && <CriticReport report={report} />}
            <div className="creation-variant-card-actions">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setExpanded((s) => ({ ...s, [v.id]: !isExpanded }))}
                disabled={disabled}
              >
                {isExpanded ? '收起' : '展开 / 查看审核'}
              </button>
              {isSel ? (
                <>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => onEdit(v)}
                    disabled={disabled}
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => onConfirm(v)}
                    disabled={disabled}
                  >
                    确认本章 →
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => onSelect(v.id)}
                  disabled={disabled}
                >
                  选此版本
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
