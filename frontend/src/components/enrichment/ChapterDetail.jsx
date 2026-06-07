import { useEffect, useState } from 'react';

const STEP_LABELS = {
  summary: '内容总结',
  recognition: '人物事件识别',
  rewrite: 'AI 改写',
};

function StatusBadge({ status }) {
  if (!status || status === 'pending') {
    return <span className="status-pill status-pending">待处理</span>;
  }
  if (status === 'running') {
    return <span className="status-pill status-running">进行中</span>;
  }
  if (status === 'done') {
    return <span className="status-pill status-parsed">已完成</span>;
  }
  if (status === 'failed') {
    return <span className="status-pill status-failed">失败</span>;
  }
  return <span className="status-pill">{status}</span>;
}

function StepButton({ label, status, onClick, busy }) {
  return (
    <button
      type="button"
      className="enrichment-detail-step-btn"
      onClick={onClick}
      disabled={busy}
      title={status === 'failed' ? '重新生成' : '执行该步骤'}
    >
      {busy ? <span className="loading-spinner small" /> : null}
      {label}
      <StatusBadge status={status} />
    </button>
  );
}

function Card({ title, status, error, onRegenerate, regenerating, children, actions }) {
  return (
    <div className="enrichment-detail-card">
      <header className="enrichment-detail-card-head">
        <h3>{title}</h3>
        <div className="enrichment-detail-card-head-right">
          {status && <StatusBadge status={status} />}
          {actions}
          {onRegenerate && (
            <button
              type="button"
              className="enrichment-detail-regen"
              onClick={onRegenerate}
              disabled={regenerating}
              title="重新生成"
            >
              {regenerating ? (
                <span className="loading-spinner small" />
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path d="M23 4v6h-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M1 20v-6h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
              重新生成
            </button>
          )}
        </div>
      </header>
      <div className="enrichment-detail-card-body">{children}</div>
      {error && status === 'failed' && (
        <div className="enrichment-detail-card-error">{error}</div>
      )}
    </div>
  );
}

function SummaryCard({ detail, onRegenerate, regenerating }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(detail.summary || '');
  useEffect(() => {
    setDraft(detail.summary || '');
  }, [detail.chapter_id, detail.summary]);

  return (
    <Card
      title="情节概要"
      status={detail.summary_status}
      error={detail.summary_error}
      onRegenerate={onRegenerate}
      regenerating={regenerating}
      actions={
        detail.summary_status === 'done' && !editing ? (
          <button
            type="button"
            className="enrichment-detail-edit"
            onClick={() => setEditing(true)}
            title="编辑"
          >
            编辑
          </button>
        ) : editing ? (
          <>
            <button
              type="button"
              className="enrichment-detail-edit"
              onClick={async () => {
                await onRegenerate(undefined, draft);
                setEditing(false);
              }}
            >
              保存
            </button>
            <button
              type="button"
              className="enrichment-detail-edit ghost"
              onClick={() => {
                setEditing(false);
                setDraft(detail.summary || '');
              }}
            >
              取消
            </button>
          </>
        ) : null
      }
    >
      {editing ? (
        <textarea
          className="enrichment-detail-textarea"
          rows={5}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      ) : detail.summary ? (
        <p className="enrichment-detail-summary-text">{detail.summary}</p>
      ) : (
        <p className="enrichment-detail-empty">尚未生成，点击「重新生成」调用 AI 摘要。</p>
      )}
    </Card>
  );
}

function RecognitionCard({ detail, onRegenerate, regenerating }) {
  const rec = detail.recognition || {};
  const characters = Array.isArray(rec.characters) ? rec.characters : [];
  const events = Array.isArray(rec.events) ? rec.events : [];
  return (
    <Card
      title="登场人物 / 关键事件"
      status={detail.recognition_status}
      error={detail.recognition_error}
      onRegenerate={onRegenerate}
      regenerating={regenerating}
    >
      {detail.recognition_status === 'done' ? (
        <div className="enrichment-detail-recognition">
          <div className="enrichment-detail-rec-section">
            <h4>登场人物</h4>
            {characters.length === 0 ? (
              <p className="enrichment-detail-empty small">未识别到人物</p>
            ) : (
              <ul className="enrichment-detail-characters">
                {characters.map((c, idx) => (
                  <li key={idx}>
                    <span className="enrichment-detail-char-name">
                      {c.name || c.id || `人物${idx + 1}`}
                    </span>
                    {c.description && (
                      <span className="enrichment-detail-char-desc">
                        {c.description}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="enrichment-detail-rec-section">
            <h4>关键事件</h4>
            {events.length === 0 ? (
              <p className="enrichment-detail-empty small">未识别到事件</p>
            ) : (
              <ol className="enrichment-detail-events">
                {events.map((e, idx) => (
                  <li key={idx}>
                    <span className="enrichment-detail-event-name">
                      {e.name || `事件${idx + 1}`}
                    </span>
                    {e.description && (
                      <span className="enrichment-detail-event-desc">
                        {e.description}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>
          {rec.scene_tag && (
            <div className="enrichment-detail-scene">
              <span className="enrichment-detail-scene-label">场景标签</span>
              <span className="enrichment-detail-scene-tag">{rec.scene_tag}</span>
            </div>
          )}
        </div>
      ) : (
        <p className="enrichment-detail-empty">
          尚未识别，点击「重新生成」让 AI 抽取登场人物与关键事件。
        </p>
      )}
    </Card>
  );
}

function RewriteCard({ detail, onRegenerate, regenerating, modelConfigId }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(detail.rewrite_text || '');
  useEffect(() => {
    setDraft(detail.rewrite_text || '');
  }, [detail.chapter_id, detail.rewrite_text]);

  return (
    <Card
      title="AI 改写正文"
      status={detail.rewrite_status}
      error={detail.rewrite_error}
      onRegenerate={onRegenerate}
      regenerating={regenerating}
      actions={
        detail.rewrite_status === 'done' && !editing ? (
          <button
            type="button"
            className="enrichment-detail-edit"
            onClick={() => setEditing(true)}
            title="编辑"
          >
            编辑
          </button>
        ) : editing ? (
          <>
            <button
              type="button"
              className="enrichment-detail-edit"
              onClick={async () => {
                await onRegenerate(undefined, draft);
                setEditing(false);
              }}
            >
              保存
            </button>
            <button
              type="button"
              className="enrichment-detail-edit ghost"
              onClick={() => {
                setEditing(false);
                setDraft(detail.rewrite_text || '');
              }}
            >
              取消
            </button>
          </>
        ) : null
      }
    >
      {editing ? (
        <textarea
          className="enrichment-detail-textarea large"
          rows={16}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      ) : detail.rewrite_text ? (
        <pre className="enrichment-detail-rewrite-text">{detail.rewrite_text}</pre>
      ) : (
        <p className="enrichment-detail-empty">
          尚未改写，点击「重新生成」让 AI 加料改写本章正文。
        </p>
      )}
    </Card>
  );
}

function OriginalCard({ detail }) {
  const [open, setOpen] = useState(false);
  if (!detail.content) return null;
  return (
    <div className="enrichment-detail-card enrichment-detail-original">
      <header className="enrichment-detail-card-head">
        <h3>原文 (参考)</h3>
        <button
          type="button"
          className="enrichment-detail-edit ghost"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? '收起' : '展开'}
        </button>
      </header>
      {open && <pre className="enrichment-detail-rewrite-text">{detail.content}</pre>}
    </div>
  );
}

export function ChapterDetail({
  detail,
  loading,
  onRegenerateStep,
  runningStep,
  onRegenerateAll,
  runningAll,
}) {
  if (loading) {
    return (
      <div className="enrichment-detail-loading">
        <div className="loading-spinner large" />
        <p>加载章节加料详情...</p>
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="library-empty">
        <p>从左侧选择一章查看加料详情</p>
      </div>
    );
  }
  return (
    <div className="enrichment-detail">
      <header className="enrichment-detail-head">
        <div className="enrichment-detail-head-title">
          <h2>
            第 {detail.chapter_number} 章 {detail.title}
          </h2>
          <span className="enrichment-detail-word-count">{detail.word_count} 字</span>
          {detail.scene_tag && (
            <span className="enrichment-detail-scene-tag">{detail.scene_tag}</span>
          )}
        </div>
        <div className="enrichment-detail-head-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={runningAll}
            onClick={onRegenerateAll}
          >
            {runningAll ? (
              <span className="loading-spinner small" />
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M23 4v6h-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M1 20v-6h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
            一键重跑本章节
          </button>
        </div>
      </header>

      <div className="enrichment-detail-step-buttons">
        <StepButton
          label={STEP_LABELS.summary}
          status={detail.summary_status}
          onClick={() => onRegenerateStep('summary')}
          busy={runningStep === 'summary'}
        />
        <StepButton
          label={STEP_LABELS.recognition}
          status={detail.recognition_status}
          onClick={() => onRegenerateStep('recognition')}
          busy={runningStep === 'recognition'}
        />
        <StepButton
          label={STEP_LABELS.rewrite}
          status={detail.rewrite_status}
          onClick={() => onRegenerateStep('rewrite')}
          busy={runningStep === 'rewrite'}
        />
      </div>

      <SummaryCard
        detail={detail}
        regenerating={runningStep === 'summary'}
        onRegenerate={(step, manualSummary) =>
          onRegenerateStep('summary', { manualSummary })
        }
      />
      <RecognitionCard
        detail={detail}
        regenerating={runningStep === 'recognition'}
        onRegenerate={() => onRegenerateStep('recognition')}
      />
      <RewriteCard
        detail={detail}
        regenerating={runningStep === 'rewrite'}
        onRegenerate={(step, manualRewrite) =>
          onRegenerateStep('rewrite', { manualRewrite })
        }
      />
      <OriginalCard detail={detail} />
    </div>
  );
}