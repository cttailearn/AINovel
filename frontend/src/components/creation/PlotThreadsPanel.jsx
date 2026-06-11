// P1-#6: 剧情线索 (PlotThread) 手动管理面板
// - 列表 / 新增 / 编辑 / 删除 / 改状态 (open→hinting→resolved/dropped)
// - 状态变更 ConfirmDialog (删除时)
import { useEffect, useState } from 'react';
import { ApiError, api } from '../../api/client.js';
import { useToast } from '../Toast/ToastProvider.jsx';
import { useConfirm } from '../../hooks/ConfirmProvider.jsx';

const STATUS_OPTIONS = [
  { value: 'open', label: '未结' },
  { value: 'hinting', label: '埋线' },
  { value: 'resolving', label: '收线中' },
  { value: 'resolved', label: '已回收' },
  { value: 'dropped', label: '已放弃' },
];
const TYPE_OPTIONS = ['伏笔', '阴谋', '角色弧', '主题弧', '承诺', '其他'];

function statusLabel(s) {
  return STATUS_OPTIONS.find((o) => o.value === s)?.label || s;
}

function ThreadForm({ initial, onSubmit, onCancel, submitting }) {
  const [title, setTitle] = useState(initial?.title || '');
  const [threadType, setThreadType] = useState(initial?.thread_type || '伏笔');
  const [status, setStatus] = useState(initial?.status || 'open');
  const [priority, setPriority] = useState(initial?.priority || 3);
  const [notes, setNotes] = useState(initial?.notes || '');

  const handleSubmit = (e) => {
    e?.preventDefault?.();
    if (!title.trim()) return;
    onSubmit({
      title: title.trim(),
      thread_type: threadType,
      status,
      priority: Number(priority) || 3,
      notes: notes.trim(),
    });
  };

  return (
    <form className="creation-thread-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <label className="form-label">标题 <span className="required">*</span></label>
        <input
          className="form-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          autoFocus
          placeholder="如: 主角身世之谜"
        />
      </div>
      <div className="form-row form-row-2">
        <div>
          <label className="form-label">类型</label>
          <select className="form-input" value={threadType} onChange={(e) => setThreadType(e.target.value)}>
            {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="form-label">状态</label>
          <select className="form-input" value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUS_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>
      </div>
      <div className="form-row">
        <label className="form-label">优先级: {priority}/5</label>
        <input
          type="range" min="1" max="5" step="1"
          value={priority} onChange={(e) => setPriority(Number(e.target.value))}
        />
      </div>
      <div className="form-row">
        <label className="form-label">备注</label>
        <textarea
          className="form-input form-textarea" rows={2}
          value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder="可写章节关联 / 预期回收时机 / 关键提示词..."
        />
      </div>
      <div className="form-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel} disabled={submitting}>取消</button>
        <button type="submit" className="btn btn-primary btn-sm" disabled={submitting || !title.trim()}>
          {submitting ? '保存中…' : (initial ? '保存修改' : '新增线索')}
        </button>
      </div>
    </form>
  );
}

export function PlotThreadsPanel({ projectId, refreshKey = 0, onChange }) {
  const toast = useToast();
  const confirmDialog = useConfirm();
  const [threads, setThreads] = useState([]);
  const [loading, setLoading] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const reload = async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const data = await api.creation.listPlotThreads(projectId);
      setThreads(data.threads || []);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '加载线索失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [projectId, refreshKey]);

  const handleCreate = async (payload) => {
    setSubmitting(true);
    try {
      await api.creation.createPlotThread(projectId, payload);
      toast.success('已新增线索');
      setCreating(false);
      await reload();
      onChange?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '新增失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async (threadId, payload) => {
    setSubmitting(true);
    try {
      await api.creation.updatePlotThread(projectId, threadId, payload);
      toast.success('已保存');
      setEditingId(null);
      await reload();
      onChange?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (t) => {
    const ok = await confirmDialog({
      title: '删除线索',
      message: `确认删除线索「${t.title}」? 此操作不可恢复.`,
      danger: true,
      confirmText: '确认删除',
    });
    if (!ok) return;
    try {
      await api.creation.deletePlotThread(projectId, t.thread_id);
      toast.success('已删除');
      await reload();
      onChange?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '删除失败');
    }
  };

  if (loading && threads.length === 0) {
    return <p className="muted small">加载线索…</p>;
  }

  const open = threads.filter((t) => t.status === 'open' || t.status === 'hinting' || t.status === 'resolving');
  const closed = threads.filter((t) => t.status === 'resolved' || t.status === 'dropped');

  return (
    <div className="creation-threads-panel">
      {!creating && (
        <button
          type="button" className="btn btn-ghost btn-sm"
          onClick={() => setCreating(true)}
          style={{ marginBottom: 8 }}
        >
          + 新增线索
        </button>
      )}
      {creating && (
        <div className="creation-thread-form-wrap">
          <ThreadForm
            onSubmit={handleCreate}
            onCancel={() => setCreating(false)}
            submitting={submitting}
          />
        </div>
      )}
      {threads.length === 0 && !creating ? (
        <p className="muted small">还没有线索. 确认章节后 AI 会自动抽取伏笔, 你也可以手动新增.</p>
      ) : (
        <>
          {open.length > 0 && (
            <ul className="creation-thread-list-detailed">
              {open.map((t) => (
                <li key={t.thread_id} className="creation-thread-row">
                  {editingId === t.thread_id ? (
                    <ThreadForm
                      initial={t}
                      submitting={submitting}
                      onSubmit={(p) => handleUpdate(t.thread_id, p)}
                      onCancel={() => setEditingId(null)}
                    />
                  ) : (
                    <>
                      <div className="creation-thread-row-head">
                        <span className="creation-thread-row-title" title={t.title}>{t.title}</span>
                        <span className={`creation-thread-status status-${t.status}`}>
                          {statusLabel(t.status)}
                        </span>
                      </div>
                      <div className="creation-thread-row-meta muted small">
                        {t.thread_type && <span>{t.thread_type}</span>}
                        <span>
                          优先级: {[1,2,3,4,5].map(n => (
                            <span key={n} className={`creation-thread-priority-dot ${
                              n <= (t.priority || 0) ? 'is-filled' : ''
                            }`} />
                          ))}
                        </span>
                      </div>
                      {t.notes && <p className="creation-thread-row-notes">{t.notes}</p>}
                      <div className="creation-thread-row-actions">
                        <button type="button" className="icon-btn"
                          onClick={() => setEditingId(t.thread_id)} title="编辑" aria-label="编辑">✎</button>
                        <button type="button" className="icon-btn"
                          onClick={() => handleUpdate(t.thread_id, { status: 'resolved', resolved_chapter_id: undefined })}
                          title="标记为已回收" aria-label="回收">✓</button>
                        <button type="button" className="icon-btn danger"
                          onClick={() => handleDelete(t)} title="删除" aria-label="删除">×</button>
                      </div>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          {closed.length > 0 && (
            <details className="creation-thread-closed">
              <summary className="muted small">已关闭 {closed.length} 条</summary>
              <ul className="creation-thread-list-detailed">
                {closed.map((t) => (
                  <li key={t.thread_id} className="creation-thread-row is-closed">
                    <div className="creation-thread-row-head">
                      <span className="creation-thread-row-title" title={t.title}>{t.title}</span>
                      <span className={`creation-thread-status status-${t.status}`}>
                        {statusLabel(t.status)}
                      </span>
                    </div>
                    <div className="creation-thread-row-actions">
                      <button type="button" className="icon-btn"
                        onClick={() => handleUpdate(t.thread_id, { status: 'open' })}
                        title="重新打开" aria-label="重开">↺</button>
                      <button type="button" className="icon-btn danger"
                        onClick={() => handleDelete(t)} title="删除" aria-label="删除">×</button>
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
