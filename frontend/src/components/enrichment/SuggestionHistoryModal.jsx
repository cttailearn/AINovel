import { useEffect, useState } from 'react';
import { ApiError, api } from '../../api/client.js';
import { useToast } from '../Toast/ToastProvider.jsx';

const STATUS_META = {
  applied: { label: '已应用', cls: 'status-applied' },
  superseded: { label: '已被新版本取代', cls: 'status-superseded' },
  reverted: { label: '已回滚', cls: 'status-reverted' },
};

function formatTime(t) {
  if (!t) return '—';
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return String(t);
  }
}

export function SuggestionHistoryModal({ chapterId, onClose, onReverted }) {
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState([]);
  const [revertingId, setRevertingId] = useState(null);

  useEffect(() => {
    if (!chapterId) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await api.enrichment.history(chapterId);
        if (!cancelled) setItems(data.items || []);
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载历史失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chapterId, toast]);

  const handleRevert = async (targetId) => {
    if (!chapterId) return;
    setRevertingId(targetId);
    try {
      await api.enrichment.revert(chapterId, { target_suggestion_id: targetId });
      toast.success('已回滚到该版本');
      // 刷新
      const data = await api.enrichment.history(chapterId);
      setItems(data.items || []);
      onReverted?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '回滚失败');
    } finally {
      setRevertingId(null);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card suggestion-history-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-header">
          <h3>加料应用历史</h3>
          <button type="button" onClick={onClose} title="关闭">
            ×
          </button>
        </header>
        <div className="modal-body">
          {loading ? (
            <div className="library-list-loading">
              <div className="loading-spinner small" />
              <span>载入历史...</span>
            </div>
          ) : items.length === 0 ? (
            <p className="modal-empty">该章节尚无应用记录</p>
          ) : (
            <ul className="suggestion-history-list">
              {items.map((it) => {
                const meta = STATUS_META[it.status] || STATUS_META.applied;
                const isCurrent = it.status === 'applied';
                return (
                  <li
                    key={it.id}
                    className={`suggestion-history-item ${meta.cls} ${
                      isCurrent ? 'is-current' : ''
                    }`}
                  >
                    <div className="suggestion-history-row">
                      <span className="suggestion-history-id">#{it.id}</span>
                      <span className={`suggestion-history-status ${meta.cls}`}>
                        {meta.label}
                      </span>
                      <span className="suggestion-history-time">
                        {formatTime(it.applied_at)}
                      </span>
                    </div>
                    <div className="suggestion-history-stats">
                      <span>
                        原 {it.original_length.toLocaleString()} 字
                      </span>
                      <span>
                        改 {it.rewrite_length.toLocaleString()} 字
                      </span>
                      <span className="stat-added">
                        新增 +{it.added_length.toLocaleString()}
                      </span>
                      <span className="stat-removed">
                        删除 -{it.removed_length.toLocaleString()}
                      </span>
                      {it.scene_tag && (
                        <span className="suggestion-history-scene">
                          场景 {it.scene_tag}
                        </span>
                      )}
                    </div>
                    {!isCurrent && (
                      <div className="suggestion-history-actions">
                        <button
                          type="button"
                          className="btn btn-ghost small"
                          onClick={() => handleRevert(it.id)}
                          disabled={revertingId === it.id}
                        >
                          {revertingId === it.id ? '回滚中…' : '回滚到该版本'}
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <footer className="modal-footer">
          <button type="button" className="btn" onClick={onClose}>
            关闭
          </button>
        </footer>
      </div>
    </div>
  );
}
