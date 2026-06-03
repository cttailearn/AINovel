import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';
import { KnowledgeGraphPanel } from './KnowledgeGraphPanel.jsx';

function StatusPill({ status }) {
  if (status === 'parsed') {
    return <span className="atelier-pill">已解析</span>;
  }
  if (status === 'pending') {
    return <span className="atelier-pill muted">待解析</span>;
  }
  return <span className="atelier-pill muted">{status}</span>;
}

function KgCountBadge({ stats, loading }) {
  if (loading) {
    return <span className="atelier-pill muted skeleton-dot">—</span>;
  }
  if (!stats || (stats.characters === 0 && stats.events === 0)) {
    return <span className="atelier-pill muted">未抽取</span>;
  }
  return (
    <span className="atelier-pill">
      {stats.characters} <span style={{ opacity: 0.6 }}>人</span>
      {' / '}
      {stats.events} <span style={{ opacity: 0.6 }}>事</span>
    </span>
  );
}

function NovelListItem({ novel, stats, statsLoading, active, onSelect }) {
  return (
    <button
      type="button"
      className={`atelier-item ${active ? 'selected' : ''}`}
      onClick={() => onSelect(novel.id)}
    >
      <div className="atelier-item-head">
        <h4 className="atelier-item-name" title={novel.title}>
          {novel.title}
        </h4>
        <StatusPill status={novel.status} />
      </div>
      {novel.author && (
        <p className="atelier-item-desc">
          {novel.author}
          {novel.filename && (
            <span style={{ opacity: 0.65 }}> · {novel.filename}</span>
          )}
        </p>
      )}
      <div className="atelier-item-foot">
        <KgCountBadge stats={stats} loading={statsLoading} />
        <span>{novel.chapter_count || 0} 章</span>
      </div>
    </button>
  );
}

function EmptyDetail() {
  return (
    <div className="atelier-empty">
      <div className="atelier-empty-mark">图</div>
      <h3 className="atelier-empty-title">尚未选择任何作品</h3>
      <p className="atelier-empty-msg">
        从左侧选中一本已解析的小说，AI 会按章节分阶段抽取出人物、事件与人物/事件之间的关系，自动构建知识图谱。
      </p>
    </div>
  );
}

export function KnowledgeGraphPage({ models }) {
  const toast = useToast();
  const [novels, setNovels] = useState([]);
  const [novelsLoading, setNovelsLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [search, setSearch] = useState('');
  const [kgStats, setKgStats] = useState({});
  const [statsLoading, setStatsLoading] = useState({});

  const fetchNovels = async () => {
    setNovelsLoading(true);
    try {
      const data = await api.novels.list();
      setNovels(data.novels || []);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : '加载小说失败');
    } finally {
      setNovelsLoading(false);
    }
  };

  useEffect(() => {
    fetchNovels();
  }, []);

  const loadStats = async (novelId) => {
    if (kgStats[novelId] !== undefined) return;
    setStatsLoading((prev) => ({ ...prev, [novelId]: true }));
    try {
      const data = await api.novels.getKgStats(novelId);
      setKgStats((prev) => ({ ...prev, [novelId]: data }));
    } catch {
      setKgStats((prev) => ({
        ...prev,
        [novelId]: { characters: 0, events: 0 },
      }));
    } finally {
      setStatsLoading((prev) => ({ ...prev, [novelId]: false }));
    }
  };

  useEffect(() => {
    novels.forEach((n) => {
      if (kgStats[n.id] === undefined) {
        loadStats(n.id);
      }
    });
  }, [novels]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return novels;
    return novels.filter(
      (n) =>
        n.title.toLowerCase().includes(q) ||
        (n.author || '').toLowerCase().includes(q)
    );
  }, [novels, search]);

  const selectedNovel = useMemo(
    () => novels.find((n) => n.id === selectedId) || null,
    [novels, selectedId]
  );

  const handleExtracted = async (novelId) => {
    setKgStats((prev) => ({ ...prev, [novelId]: undefined }));
    setStatsLoading((prev) => ({ ...prev, [novelId]: true }));
    try {
      const data = await api.novels.getKgStats(novelId);
      setKgStats((prev) => ({ ...prev, [novelId]: data }));
    } catch {
      setKgStats((prev) => ({
        ...prev,
        [novelId]: { characters: 0, events: 0 },
      }));
    } finally {
      setStatsLoading((prev) => ({ ...prev, [novelId]: false }));
    }
  };

  const totalCharacters = useMemo(
    () =>
      Object.values(kgStats).reduce(
        (acc, v) => acc + (v && typeof v.characters === 'number' ? v.characters : 0),
        0
      ),
    [kgStats]
  );
  const totalEvents = useMemo(
    () =>
      Object.values(kgStats).reduce(
        (acc, v) => acc + (v && typeof v.events === 'number' ? v.events : 0),
        0
      ),
    [kgStats]
  );

  return (
    <div className="atelier-shell">
      <aside className="atelier-aside">
        <header className="atelier-aside-head">
          <span className="atelier-eyebrow">Knowledge Graph</span>
          <h2 className="atelier-title">知识图谱</h2>
          <p className="atelier-lede">
            为每本小说建立人物、事件与关系图谱，按章节分阶段抽取。
          </p>
          <div className="atelier-meta-grid">
            <div className="atelier-meta-cell">
              <span className="atelier-meta-value">{novels.length}</span>
              <span className="atelier-meta-label">作品</span>
            </div>
            <div className="atelier-meta-cell">
              <span className="atelier-meta-value">{totalCharacters}</span>
              <span className="atelier-meta-label">人物</span>
            </div>
            <div className="atelier-meta-cell">
              <span className="atelier-meta-value">{totalEvents}</span>
              <span className="atelier-meta-label">事件</span>
            </div>
          </div>
        </header>

        <div className="atelier-aside-tools">
          <label className="atelier-search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
              <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" />
            </svg>
            <input
              type="text"
              placeholder="搜索小说标题或作者..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>

        <div className="atelier-aside-list">
          {novelsLoading ? (
            <div className="atelier-list-loading">
              <div className="loading-spinner small"></div>
              <span>载入中…</span>
            </div>
          ) : filtered.length === 0 ? (
            <div className="atelier-list-empty">
              {novels.length === 0
                ? '尚未上传任何小说，请先在「工作台」中创建项目。'
                : '没有匹配的小说。'}
            </div>
          ) : (
            filtered.map((novel) => (
              <NovelListItem
                key={novel.id}
                novel={novel}
                stats={kgStats[novel.id]}
                statsLoading={!!statsLoading[novel.id]}
                active={selectedId === novel.id}
                onSelect={setSelectedId}
              />
            ))
          )}
        </div>
      </aside>

      <section className="atelier-main">
        <div className="atelier-main-head">
          <div className="atelier-main-head-left">
            <span className="atelier-eyebrow">Graph Workspace</span>
            <h1 className="atelier-main-title">
              {selectedNovel ? selectedNovel.title : '尚未选择作品'}
            </h1>
            <p className="atelier-main-subtitle">
              {selectedNovel
                ? '查看与构建本作品的人物、事件与关系图谱。可一键重新抽取以纳入最新章节。'
                : '从左侧选择一本已上传的小说，开始构建知识图谱。'}
            </p>
          </div>
        </div>
        {selectedNovel ? (
          <KnowledgeGraphPanel
            key={selectedNovel.id}
            novelId={selectedNovel.id}
            models={models}
            novelTitle={selectedNovel.title}
            onExtracted={() => handleExtracted(selectedNovel.id)}
          />
        ) : (
          <EmptyDetail />
        )}
      </section>
    </div>
  );
}
