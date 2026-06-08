import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../../api/client.js';
import { useToast } from '../Toast/ToastProvider.jsx';

/**
 * 拆分专属子页. 展示当前小说的章节列表 + 起止位置 + 字数.
 * - 数据源: GET /api/novels/{id}/chapters
 * - 不直接修改, 修改走 Workbench 的 "解析目录"
 */
export function SplitView({ novel, onJumpToParse, onJumpToChapter }) {
  const toast = useToast();
  const [chapters, setChapters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (!novel?.id) {
      setChapters([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await api.novels.detail(novel.id);
        if (cancelled) return;
        setChapters(data?.chapters || []);
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof ApiError ? err.message : '加载章节失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [novel?.id, toast]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return chapters;
    return chapters.filter(
      (c) =>
        String(c.chapter_number).includes(q) ||
        (c.title || '').toLowerCase().includes(q)
    );
  }, [chapters, query]);

  const total = chapters.length;
  const totalLen = chapters.reduce(
    (acc, c) =>
      acc +
      (Number(c.end_position || 0) > Number(c.start_position || 0)
        ? Number(c.end_position) - Number(c.start_position)
        : 0),
    0
  );

  return (
    <div className="enrichment-split-view">
      <header className="enrichment-split-view-head">
        <div>
          <h3>书籍拆分</h3>
          <p>
            共 {total} 章 · 约 {totalLen.toLocaleString()} 字符
          </p>
        </div>
        <div className="enrichment-split-view-tools">
          <label className="project-search-bar small">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
              <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" />
            </svg>
            <input
              type="text"
              placeholder="搜索章节号 / 标题"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onJumpToParse}
            title="跳到解析目录"
          >
            重新解析 →
          </button>
        </div>
      </header>

      {loading ? (
        <div className="library-list-loading">
          <div className="loading-spinner small" />
          <span>载入章节...</span>
        </div>
      ) : chapters.length === 0 ? (
        <div className="library-list-empty">
          <p>该书尚未解析章节</p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onJumpToParse}
          >
            去解析章节
          </button>
        </div>
      ) : (
        <div className="enrichment-split-table-wrap">
          <table className="enrichment-split-table">
            <thead>
              <tr>
                <th style={{ width: 60 }}>#</th>
                <th>标题</th>
                <th style={{ width: 120 }}>起始</th>
                <th style={{ width: 120 }}>结束</th>
                <th style={{ width: 100 }}>字数</th>
                <th style={{ width: 100 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const start = Number(c.start_position || 0);
                const end = Number(c.end_position || 0);
                const len = end > start ? end - start : 0;
                return (
                  <tr key={c.id}>
                    <td className="enrichment-split-num">{c.chapter_number}</td>
                    <td className="enrichment-split-title">{c.title || '—'}</td>
                    <td className="enrichment-split-pos">{start.toLocaleString()}</td>
                    <td className="enrichment-split-pos">{end.toLocaleString()}</td>
                    <td className="enrichment-split-len">{len.toLocaleString()}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost small"
                        onClick={() => onJumpToChapter?.(c.id)}
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="enrichment-split-empty">
                    没有匹配的章节
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
