import { useEffect, useMemo, useState } from 'react';

const PHASES = [
  { key: 'characters', label: '抽取人物' },
  { key: 'events', label: '抽取事件' },
  { key: 'participations', label: '参与关系' },
  { key: 'char_relations', label: '人物关系' },
  { key: 'event_relations', label: '事件关系' },
];

/**
 * Visualizes the live extraction pipeline.
 *
 * Props:
 *   - status: 'idle' | 'running' | 'done' | 'error'
 *   - progress: { percent, message, phase, done, total, ... }
 *   - phaseStats: { characters, events, participations, char_relations, event_relations, count }
 *   - error: optional error string
 *   - onCancel: optional cancel callback
 */
export function ExtractionProgress({ status, progress, phaseStats, error, onCancel }) {
  const percent = Math.max(0, Math.min(100, Number(progress?.percent || 0)));
  const activePhase = progress?.phase;
  const logs = useLogStream(progress);

  if (status === 'idle') return null;

  return (
    <div className={`kg-progress kg-progress-${status}`}>
      <header className="kg-progress-head">
        <div className="kg-progress-title">
          {status === 'running' && (
            <span className="kg-progress-dot running"></span>
          )}
          {status === 'done' && (
            <span className="kg-progress-dot done"></span>
          )}
          {status === 'error' && (
            <span className="kg-progress-dot error"></span>
          )}
          <span>
            {status === 'running' && '正在构建知识图谱'}
            {status === 'done' && '构建完成'}
            {status === 'error' && '构建失败'}
          </span>
        </div>
        <div className="kg-progress-percent">
          {status === 'running' && `${percent.toFixed(0)}%`}
          {status === 'done' && '100%'}
          {status === 'error' && '—'}
        </div>
      </header>
      <div className="kg-progress-track">
        <div
          className="kg-progress-bar"
          style={{ width: `${status === 'done' ? 100 : percent}%` }}
        />
      </div>
      <div className="kg-progress-phases">
        {PHASES.map((p) => {
          const stat = phaseStats?.[p.key];
          const isActive = status === 'running' && activePhase === p.key;
          const isDone = !!stat || (status === 'done');
          return (
            <div
              key={p.key}
              className={`kg-progress-phase ${isActive ? 'active' : ''} ${isDone ? 'done' : ''}`}
            >
              <span className="kg-progress-phase-label">{p.label}</span>
              <span className="kg-progress-phase-count">
                {stat?.count !== undefined ? stat.count : (isDone ? '✓' : '…')}
              </span>
            </div>
          );
        })}
      </div>
      {progress?.message && status === 'running' && (
        <p className="kg-progress-message">
          {progress.message}
          {progress.done !== undefined && progress.total !== undefined && (
            <span className="kg-progress-chunk">
              {' '}({progress.done}/{progress.total} 片段)
            </span>
          )}
        </p>
      )}
      {error && <p className="kg-progress-error">{error}</p>}
      {status === 'running' && onCancel && (
        <div className="kg-progress-actions">
          <button type="button" className="kg-progress-cancel" onClick={onCancel}>
            取消
          </button>
        </div>
      )}
      {logs.length > 0 && (
        <details className="kg-progress-log" open={status === 'error'}>
          <summary>详细日志</summary>
          <ul>
            {logs.map((l, i) => (
              <li key={i}>
                <span className="kg-progress-log-time">{l.time}</span>
                <span className="kg-progress-log-msg">{l.message}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function useLogStream(progress) {
  const [logs, setLogs] = useState([]);
  useEffect(() => {
    if (!progress?.message) return;
    setLogs((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.message === progress.message) return prev;
      const next = [
        ...prev,
        {
          time: new Date().toLocaleTimeString(),
          message: progress.message,
        },
      ];
      // Keep the tail to avoid unbounded growth.
      return next.length > 80 ? next.slice(next.length - 80) : next;
    });
  }, [progress?.message]);
  return logs;
}
