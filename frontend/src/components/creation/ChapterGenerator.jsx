// 单章节生成: 用户输入意图 → SSE 推送 Planner / Writer / Critic 进度
// 支持 regenMode: 预填标题, 显示"重新生成第 N 章", 提供取消按钮
// UX-#2: 失败时支持 retry, lastError + onRetry 由父级传入
import { useEffect, useState } from 'react';

const STAGE_LABELS = {
  start: '准备',
  planner_done: '决策完成',
  writer_0_done: '候选 1 写作完成',
  writer_1_done: '候选 2 写作完成',
  writer_2_done: '候选 3 写作完成',
  critic_0_done: '候选 1 审核完成',
  critic_1_done: '候选 2 审核完成',
  critic_2_done: '候选 3 审核完成',
  done: '全部完成',
  error: '出错',
};

function ScoreBadge({ score }) {
  if (typeof score !== 'number' || Number.isNaN(score)) return null;
  let tone = 'low';
  if (score >= 8) tone = 'high';
  else if (score >= 6) tone = 'mid';
  return <span className={`creation-score tone-${tone}`}>{score.toFixed(1)}</span>;
}

export function ChapterGenerator({
  project,
  nextChapterNo,
  onGenerate,
  onCancel,
  onCancelRegen,
  generating = false,
  progress = null,
  regenMode = false,
  initialTitle = '',
  initialUserIntent = '',
  lastError = null,
  onRetry = null,
}) {
  const [userIntent, setUserIntent] = useState(initialUserIntent || '');
  const [title, setTitle] = useState(initialTitle || '');

  // regenMode 切换时, 重置 title 为 initialTitle
  useEffect(() => {
    if (regenMode) {
      setTitle(initialTitle || '');
    } else if (!initialTitle) {
      setTitle('');
    } else {
      setTitle(initialTitle);
    }
  }, [regenMode, initialTitle]);

  // P1-#9: regen 模式预填 user_intent
  useEffect(() => {
    if (regenMode && initialUserIntent) {
      setUserIntent(initialUserIntent);
    }
  }, [regenMode, initialUserIntent]);

  if (!project) return null;

  const submitLabel = regenMode
    ? `↻ 重新生成第 ${nextChapterNo} 章`
    : `生成第 ${nextChapterNo} 章`;

  return (
    <div className="creation-generator">
      {!generating ? (
        <div className="creation-generator-form">
          {/* UX-#2: 上次失败提示 + 重试按钮 */}
          {lastError && !generating && (
            <div className="creation-retry-banner">
              <div className="creation-retry-banner-msg">
                <strong>上次生成失败</strong>: {lastError}
              </div>
              {onRetry && (
                <div className="creation-retry-banner-actions">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => onRetry({
                      user_intent: userIntent.trim() || initialUserIntent,
                      title: title.trim() || initialTitle,
                      chapter_no: nextChapterNo,
                    })}
                  >
                    ↻ 用当前参数重试
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => onRetry({
                      user_intent: userIntent.trim() || initialUserIntent,
                      title: title.trim() || initialTitle,
                      chapter_no: nextChapterNo,
                    }, { useLastParams: true })}
                    title="用上次失败时的原始参数重试, 不读取当前输入框"
                  >
                    ↻ 用上次参数重试
                  </button>
                </div>
              )}
            </div>
          )}
          {regenMode && (
            <div className="creation-regen-hint small">
              重新生成会覆盖当前章节正文. 你可以填入新的需求(可选)或留空沿用, AI 会自动评分, 不达标会重写.
            </div>
          )}
          <div className="form-row">
            <label className="form-label">本章标题 (可选)</label>
            <input
              type="text"
              className="form-input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={`第 ${nextChapterNo} 章`}
              maxLength={200}
            />
          </div>
          <div className="form-row">
            <label className="form-label">
              本轮意图 / 偏好 (可选)
              {regenMode && <span className="muted"> · 留空则沿用原意图</span>}
            </label>
            <textarea
              className="form-input form-textarea"
              rows={3}
              value={userIntent}
              onChange={(e) => setUserIntent(e.target.value)}
              placeholder={
                regenMode
                  ? '可填入新的需求 / 调整方向, 留空使用模型自动沿用'
                  : '如: 这一章主角要遇到红衣女, 推动身世线, 制造 1 处悬念...'
              }
              maxLength={4000}
            />
          </div>
          <div className="form-actions">
            {regenMode && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={onCancelRegen}
                disabled={generating}
              >
                取消
              </button>
            )}
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => onGenerate({
                user_intent: userIntent.trim(),
                title: title.trim(),
                chapter_no: nextChapterNo,
              })}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="1.6">
                <path d="M5 12l5 5L20 7" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {submitLabel}
            </button>
          </div>
        </div>
      ) : (
        <div className="creation-generator-progress">
          <div className="creation-stage-list">
            {(() => {
              // P0-#1: 阶段名根据 mode 动态生成
              // single 模式: planner → writer → critic → done, 单条流水线
              // candidates 模式: 3 候选并行, 共 9 步
              const isSingle = progress?.mode === 'single'
                || (progress?.directions?.length || 0) <= 1;
              if (isSingle) {
                const stages = [
                  ['start', '初始化'],
                  ['planner_done', '决策 Agent (Planner)'],
                  ['writer_0_done', '撰写 Agent (Writer)'],
                  ['critic_0_done', '审核 Agent (Critic)'],
                  ['done', '完成'],
                ];
                return stages.map(([key, label]) => {
                  const cur = progress?.stage;
                  const curIdx = stages.findIndex(([k]) => k === cur);
                  const thisIdx = stages.findIndex(([k]) => k === key);
                  const state = curIdx < 0 ? 'todo'
                    : thisIdx < curIdx ? 'done'
                    : thisIdx === curIdx ? 'active' : 'todo';
                  return (
                    <div key={key} className={`creation-stage stage-${state}`}>
                      <span className="creation-stage-mark">
                        {state === 'done' ? '✓' : state === 'active' ? '●' : '○'}
                      </span>
                      <span>{label}</span>
                    </div>
                  );
                });
              }
              // candidates 模式: 保留旧的 9 步
              const stages = [
                ['start', '初始化'],
                ['planner_done', '决策 Agent (Planner) · 3 个方向'],
                ['writer_0_done', '执行 Agent 1 · 动作方向'],
                ['writer_1_done', '执行 Agent 2 · 心理方向'],
                ['writer_2_done', '执行 Agent 3 · 意外方向'],
                ['critic_0_done', '审核 Agent 1'],
                ['critic_1_done', '审核 Agent 2'],
                ['critic_2_done', '审核 Agent 3'],
                ['done', '完成'],
              ];
              return stages.map(([key, label]) => {
                const cur = progress?.stage;
                const curIdx = stages.findIndex(([k]) => k === cur);
                const thisIdx = stages.findIndex(([k]) => k === key);
                const state = curIdx < 0 ? 'todo'
                  : thisIdx < curIdx ? 'done'
                  : thisIdx === curIdx ? 'active' : 'todo';
                return (
                  <div key={key} className={`creation-stage stage-${state}`}>
                    <span className="creation-stage-mark">
                      {state === 'done' ? '✓' : state === 'active' ? '●' : '○'}
                    </span>
                    <span>{label}</span>
                  </div>
                );
              });
            })()}
          </div>

          {progress?.directions && (
            <div className="creation-directions">
              <h4>Planner 决策方向</h4>
              <ol>
                {progress.directions.map((d) => (
                  <li key={d.index}>
                    <strong>[{d.focus}] {d.title}</strong> — {d.synopsis}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {progress?.variants && Object.keys(progress.variants).length > 0 && (
            <div className="creation-variant-progress">
              <h4>候选进度</h4>
              {[0, 1, 2].map((i) => {
                const v = progress.variants[i];
                if (!v) {
                  return (
                    <div key={i} className="creation-variant-row muted small">
                      候选 {i + 1}: 等待中...
                    </div>
                  );
                }
                return (
                  <div key={i} className="creation-variant-row">
                    <span>候选 {i + 1}</span>
                    <span className={`creation-variant-state state-${v.state}`}>
                      {v.state === 'writing' && '写作中...'}
                      {v.state === 'critiquing' && '审核中...'}
                      {v.state === 'done' && (
                        <>
                          完成 <ScoreBadge score={v.score} />
                          {v.word_count ? ` · ${v.word_count} 字` : ''}
                        </>
                      )}
                      {v.state === 'error' && `失败: ${v.error || ''}`}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {progress?.error && (
            <div className="creation-error">生成失败: {progress.error}</div>
          )}

          <div className="form-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onCancel}
              disabled={!generating}
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

