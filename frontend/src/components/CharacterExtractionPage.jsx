import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api/client.js';
import { useToast } from './Toast/ToastProvider.jsx';
import { CharacterPanel } from './CharacterPanel.jsx';

function StatusPill({ status }) {
  if (status === 'parsed') {
    return <span className="status-pill status-parsed">已解析</span>;
  }
  if (status === 'pending') {
    return <span className="status-pill status-pending">待解析</span>;
  }
  return <span className="status-pill">{status}</span>;
}

function CharacterCountBadge({ count, loading }) {
  if (loading) {
    return <span className="ccount-badge skeleton">—</span>;
  }
  if (!count) {
    return <span className="ccount-badge empty">未提取</span>;
  }
  return <span className="ccount-badge">{count} 位</span>;
}

function NovelListItem({ novel, count, countLoading, active, onSelect }) {
  return (
    <button
      type="button"
      className={`cex-novel-item ${active ? 'active' : ''}`}
      onClick={() => onSelect(novel.id)}
    >
      <div className="cex-novel-item-head">
        <h4 className="cex-novel-title" title={novel.title}>
          {novel.title}
        </h4>
        <StatusPill status={novel.status} />
      </div>
      <p className="cex-novel-author">
        {novel.author || '未知作者'}
        {novel.filename && (
          <span className="cex-novel-filename"> · {novel.filename}</span>
        )}
      </p>
      <div className="cex-novel-meta">
        <CharacterCountBadge count={count} loading={countLoading} />
        <span className="cex-novel-chapters">{novel.chapter_count || 0} 章</span>
      </div>
    </button>
  );
}

function EmptyDetail() {
  return (
    <div className="cex-empty-detail">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none">
        <path
          d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <h3>请选择需要提取人物的小说</h3>
      <p>
        选中左侧任意一本已解析的小说，即可使用 AI 模型识别出场人物并管理人物档案。
      </p>
    </div>
  );
}

export function CharacterExtractionPage({ models }) {
  const toast = useToast();
  const [novels, setNovels] = useState([]);
  const [novelsLoading, setNovelsLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [search, setSearch] = useState('');
  const [characterCounts, setCharacterCounts] = useState({});
  const [countsLoading, setCountsLoading] = useState({});

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

  const loadCount = async (novelId) => {
    if (characterCounts[novelId] !== undefined) return;
    setCountsLoading((prev) => ({ ...prev, [novelId]: true }));
    try {
      const data = await api.novels.listCharacters(novelId);
      setCharacterCounts((prev) => ({
        ...prev,
        [novelId]: (data.characters || []).length,
      }));
    } catch {
      setCharacterCounts((prev) => ({ ...prev, [novelId]: 0 }));
    } finally {
      setCountsLoading((prev) => ({ ...prev, [novelId]: false }));
    }
  };

  useEffect(() => {
    novels.forEach((n) => {
      if (characterCounts[n.id] === undefined) {
        loadCount(n.id);
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

  const handleSelect = (id) => {
    setSelectedId(id);
  };

  const handleExtracted = async (novelId) => {
    setCharacterCounts((prev) => ({ ...prev, [novelId]: undefined }));
    setCountsLoading((prev) => ({ ...prev, [novelId]: true }));
    try {
      const data = await api.novels.listCharacters(novelId);
      setCharacterCounts((prev) => ({
        ...prev,
        [novelId]: (data.characters || []).length,
      }));
    } catch {
      setCharacterCounts((prev) => ({ ...prev, [novelId]: 0 }));
    } finally {
      setCountsLoading((prev) => ({ ...prev, [novelId]: false }));
    }
  };

  const totalCharacters = useMemo(
    () =>
      Object.values(characterCounts).reduce(
        (acc, v) => acc + (typeof v === 'number' ? v : 0),
        0
      ),
    [characterCounts]
  );

  return (
    <div className="cex-shell">
      <aside className="cex-sidebar">
        <header className="cex-sidebar-head">
          <div>
            <h2>人物提取</h2>
            <p>为每本小说建立专属角色档案</p>
          </div>
          <div className="cex-stats">
            <div className="cex-stat">
              <span className="cex-stat-value">{novels.length}</span>
              <span className="cex-stat-label">小说</span>
            </div>
            <div className="cex-stat">
              <span className="cex-stat-value">{totalCharacters}</span>
              <span className="cex-stat-label">人物</span>
            </div>
          </div>
        </header>

        <div className="cex-search">
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
        </div>

        <div className="cex-list">
          {novelsLoading ? (
            <div className="cex-list-loading">
              <div className="loading-spinner small"></div>
              <span>加载中...</span>
            </div>
          ) : filtered.length === 0 ? (
            <div className="cex-list-empty">
              {novels.length === 0
                ? '尚未上传任何小说，请先在「工作台」中创建项目'
                : '没有匹配的小说'}
            </div>
          ) : (
            filtered.map((novel) => (
              <NovelListItem
                key={novel.id}
                novel={novel}
                count={characterCounts[novel.id]}
                countLoading={!!countsLoading[novel.id]}
                active={selectedId === novel.id}
                onSelect={handleSelect}
              />
            ))
          )}
        </div>
      </aside>

      <section className="cex-detail">
        {selectedNovel ? (
          <CharacterPanel
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
