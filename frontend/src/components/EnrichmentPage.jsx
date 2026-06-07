import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';
import { EnrichmentWorkbench } from './EnrichmentWorkbench.jsx';

function StatusPill({ status }) {
  if (status === 'parsed') {
    return <span className="status-pill status-parsed">已解析</span>;
  }
  if (status === 'pending') {
    return <span className="status-pill status-pending">待解析</span>;
  }
  return <span className="status-pill">{status}</span>;
}

function ProgressBadge({ percent, total, done }) {
  if (!total) {
    return <span className="status-pill status-pending">未开始</span>;
  }
  if (percent >= 99.5) {
    return <span className="status-pill status-parsed">已完成</span>;
  }
  return (
    <span className="status-pill status-progress">
      {done}/{total}
    </span>
  );
}

function NovelListItem({ novel, progress, progressLoading, active, onSelect }) {
  return (
    <button
      type="button"
      className={`library-item ${active ? 'selected' : ''}`}
      onClick={() => onSelect(novel.id)}
    >
      <div className="library-item-head">
        <h4 className="library-item-name" title={novel.title}>
          {novel.title}
        </h4>
        <StatusPill status={novel.status} />
      </div>
      {novel.author && (
        <p className="library-item-desc">
          {novel.author}
          {novel.filename && (
            <span style={{ opacity: 0.65 }}> · {novel.filename}</span>
          )}
        </p>
      )}
      <div className="library-item-foot">
        <ProgressBadge
          percent={progress?.overall_percent}
          total={progress?.total}
          done={
            (progress?.summary_done || 0) +
            (progress?.recognition_done || 0) +
            (progress?.rewrite_done || 0)
          }
        />
        <span>{novel.chapter_count || 0} 章</span>
      </div>
    </button>
  );
}

function EmptyDetail({ hasAny }) {
  return (
    <div className="library-empty">
      <svg width="56" height="56" viewBox="0 0 24 24" fill="none" strokeWidth="1.5">
        <path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12" stroke="currentColor" strokeLinecap="round" />
        <circle cx="12" cy="12" r="4" stroke="currentColor" />
      </svg>
      <p>{hasAny ? '尚未选择作品' : '还没有可加料的小说'}</p>
      <span>
        {hasAny
          ? '从左侧选中一本已解析的小说，AI 会按章节分阶段完成摘要、人物事件识别与加料改写。'
          : '请先在工作台中上传 TXT 小说并完成章节解析。'}
      </span>
    </div>
  );
}

export function EnrichmentPage({ models, topSearch = '' }) {
  const toast = useToast();
  const [novels, setNovels] = useState([]);
  const [novelsLoading, setNovelsLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [progressMap, setProgressMap] = useState({});
  const [progressLoading, setProgressLoading] = useState({});

  const fetchNovels = async () => {
    setNovelsLoading(true);
    try {
      const data = await api.novels.list();
      // 只显示已解析章节的（chapter_count > 0）
      setNovels((data.novels || []).filter((n) => (n.chapter_count || 0) > 0));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '加载小说失败');
    } finally {
      setNovelsLoading(false);
    }
  };

  useEffect(() => {
    fetchNovels();
  }, []);

  const loadProgress = async (novelId) => {
    if (progressMap[novelId] !== undefined) return;
    setProgressLoading((prev) => ({ ...prev, [novelId]: true }));
    try {
      const data = await api.enrichment.listProgress(novelId);
      setProgressMap((prev) => ({ ...prev, [novelId]: data }));
    } catch {
      setProgressMap((prev) => ({ ...prev, [novelId]: null }));
    } finally {
      setProgressLoading((prev) => ({ ...prev, [novelId]: false }));
    }
  };

  useEffect(() => {
    novels.forEach((n) => {
      if (progressMap[n.id] === undefined) {
        loadProgress(n.id);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novels]);

  const filtered = useMemo(() => {
    const q = topSearch.trim().toLowerCase();
    if (!q) return novels;
    return novels.filter(
      (n) =>
        n.title.toLowerCase().includes(q) ||
        (n.author || '').toLowerCase().includes(q)
    );
  }, [novels, topSearch]);

  const selectedNovel = useMemo(
    () => novels.find((n) => n.id === selectedId) || null,
    [novels, selectedId]
  );

  const handleProgressChange = async (novelId) => {
    setProgressMap((prev) => ({ ...prev, [novelId]: undefined }));
    setProgressLoading((prev) => ({ ...prev, [novelId]: true }));
    try {
      const data = await api.enrichment.listProgress(novelId);
      setProgressMap((prev) => ({ ...prev, [novelId]: data }));
    } catch {
      setProgressMap((prev) => ({ ...prev, [novelId]: null }));
    } finally {
      setProgressLoading((prev) => ({ ...prev, [novelId]: false }));
    }
  };

  const totalChapters = useMemo(
    () => novels.reduce((acc, n) => acc + (n.chapter_count || 0), 0),
    [novels]
  );

  const overallDone = useMemo(() => {
    let sum = 0;
    let total = 0;
    Object.values(progressMap).forEach((p) => {
      if (!p) return;
      const completed =
        (p.summary_done || 0) + (p.recognition_done || 0) + (p.rewrite_done || 0);
      sum += completed;
      total += (p.total || 0) * 3;
    });
    if (!total) return 0;
    return Math.round((sum / total) * 100);
  }, [progressMap]);

  return (
    <div className="library-shell">
      <aside className="library-aside">
        <header className="library-aside-head">
          <span className="library-aside-eyebrow">Enrichment</span>
          <h2 className="library-aside-title">加料工作台</h2>
          <p className="library-aside-lede">
            为每本已解析章节的小说分阶段执行：内容摘要 → 人物事件识别 → AI 改写加料。
          </p>
          <div className="library-aside-meta">
            <div className="library-meta-cell">
              <span className="library-meta-value">{novels.length}</span>
              <span className="library-meta-label">作品</span>
            </div>
            <div className="library-meta-cell">
              <span className="library-meta-value">{totalChapters}</span>
              <span className="library-meta-label">章节</span>
            </div>
            <div className="library-meta-cell">
              <span className="library-meta-value">{overallDone}%</span>
              <span className="library-meta-label">完成度</span>
            </div>
          </div>
        </header>

        <div className="library-aside-list">
          {novelsLoading ? (
            <div className="library-list-loading">
              <div className="loading-spinner small"></div>
              <span>载入中…</span>
            </div>
          ) : filtered.length === 0 ? (
            <div className="library-list-empty">
              {novels.length === 0
                ? '还没有可加料的小说，请先在「工作台」中上传并解析章节。'
                : '没有匹配的小说。'}
            </div>
          ) : (
            filtered.map((novel) => (
              <NovelListItem
                key={novel.id}
                novel={novel}
                progress={progressMap[novel.id]}
                progressLoading={!!progressLoading[novel.id]}
                active={selectedId === novel.id}
                onSelect={setSelectedId}
              />
            ))
          )}
        </div>
      </aside>

      <section className="library-main">
        {selectedNovel ? (
          <EnrichmentWorkbench
            key={selectedNovel.id}
            novelId={selectedNovel.id}
            novel={selectedNovel}
            models={models}
            onProgressChange={() => handleProgressChange(selectedNovel.id)}
          />
        ) : (
          <EmptyDetail hasAny={novels.length > 0} />
        )}
      </section>
    </div>
  );
}