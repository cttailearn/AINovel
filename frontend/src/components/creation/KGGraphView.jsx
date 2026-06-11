// P1-#11: 知识图谱交互式视图 (自实现 pan/zoom, 无新依赖)
// - 鼠标拖拽 pan, 滚轮 zoom
// - 节点点击弹属性详情
// - 节点大小 ∝ importance
// - 字符/事件/地点分层布局
// - 边: 人物↔事件 (参与), 人物↔人物, 事件↔事件
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const COLORS = {
  character: { fill: '#dbeafe', stroke: '#3b82f6', text: '#1e3a8a' },
  event:     { fill: '#fed7aa', stroke: '#f97316', text: '#7c2d12' },
  location:  { fill: '#d1fae5', stroke: '#10b981', text: '#064e3b' },
};
const MAX_NODES_PER_RING = 24;

function layoutRing(items, radius, cx, cy) {
  if (!items.length) return [];
  const n = Math.min(items.length, MAX_NODES_PER_RING);
  const step = (Math.PI * 2) / n;
  return items.slice(0, n).map((it, i) => {
    const angle = -Math.PI / 2 + step * i;
    return {
      ...it,
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    };
  });
}

function radiusForImportance(imp) {
  if (imp >= 5) return 18;
  if (imp >= 4) return 16;
  if (imp >= 3) return 14;
  if (imp >= 2) return 12;
  return 10;
}

export function KGGraphView({
  characters = [],
  events = [],
  locations = [],
  characterRelations = [],
  characterEventRelations = [],
  eventRelations = [],
  onNodeClick,
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [selectedId, setSelectedId] = useState(null);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef(null);
  const svgRef = useRef(null);

  const size = 480;
  const cx = size / 2;
  const cy = size / 2;

  const layout = useMemo(() => {
    const chars = [...characters]
      .sort((a, b) => (b.importance || 0) - (a.importance || 0))
      .map((c) => ({ ...c, kind: 'character' }));
    const evs = [...events]
      .sort((a, b) => (b.importance || 0) - (a.importance || 0))
      .map((e) => ({ ...e, kind: 'event' }));
    const locs = [...locations]
      .sort((a, b) => (b.attributes?.importance || 0) - (a.attributes?.importance || 0))
      .map((l) => ({ ...l, kind: 'location' }));

    const charNodes = layoutRing(chars, 110, cx, cy);
    const eventNodes = layoutRing(evs, 180, cx, cy);
    const locNodes = layoutRing(locs, 235, cx, cy);

    const allNodes = [...charNodes, ...eventNodes, ...locNodes];
    const byId = {};
    for (const n of allNodes) byId[n.entity_id] = n;
    return { allNodes, byId };
  }, [characters, events, locations, cx, cy]);

  const { allNodes, byId } = layout;

  const allRels = useMemo(() => [
    ...characterRelations.map((r) => ({ ...r, type: 'cc' })),
    ...characterEventRelations.map((r) => ({ ...r, type: 'ce' })),
    ...eventRelations.map((r) => ({ ...r, type: 'ee' })),
  ], [characterRelations, characterEventRelations, eventRelations]);

  // 滚轮 zoom
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    setZoom((z) => {
      const delta = e.deltaY < 0 ? 0.1 : -0.1;
      const next = Math.max(0.4, Math.min(3, z + delta));
      return next;
    });
  }, []);

  // 拖拽 pan
  const handleMouseDown = (e) => {
    if (e.target.closest('[data-node-id]')) return; // 节点不触发 pan
    setDragging(true);
    dragRef.current = { startX: e.clientX, startY: e.clientY, origin: { ...pan } };
  };
  const handleMouseMove = useCallback((e) => {
    if (!dragging || !dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setPan({
      x: dragRef.current.origin.x + dx,
      y: dragRef.current.origin.y + dy,
    });
  }, [dragging]);
  const handleMouseUp = useCallback(() => {
    setDragging(false);
    dragRef.current = null;
  }, []);

  useEffect(() => {
    if (!dragging) return undefined;
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [dragging, handleMouseMove, handleMouseUp]);

  // 节点点击
  const handleNodeClick = (n) => (e) => {
    e.stopPropagation();
    setSelectedId(n.entity_id);
    onNodeClick?.(n);
  };

  // 双击空白处重置视图
  const handleDoubleClick = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSelectedId(null);
  };

  if (allNodes.length === 0) {
    return (
      <p className="muted small" style={{ textAlign: 'center', padding: '24px 0' }}>
        知识图谱暂无实体. 确认章节后会自动抽取.
      </p>
    );
  }

  // 渲染边
  const renderEdge = (rel, idx) => {
    const src = byId[rel.source_entity_id];
    const tgt = byId[rel.target_entity_id];
    if (!src || !tgt) return null;
    const stroke = rel.type === 'cc' ? '#6366f1'
                 : rel.type === 'ce' ? '#9ca3af'
                 : '#f97316';
    const strokeWidth = rel.type === 'cc' ? 1.2 : 0.8;
    const dasharray = rel.type === 'ee' ? '3,3' : null;
    return (
      <line
        key={`e-${idx}`}
        x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
        stroke={stroke} strokeWidth={strokeWidth} opacity={0.5}
        strokeDasharray={dasharray}
      />
    );
  };

  const selected = selectedId ? byId[selectedId] : null;

  return (
    <div className="kg-graph-wrap" style={{ position: 'relative' }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${size} ${size}`}
        className="kg-graph-svg"
        preserveAspectRatio="xMidYMid meet"
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onDoubleClick={handleDoubleClick}
        style={{ cursor: dragging ? 'grabbing' : 'grab', userSelect: 'none' }}
      >
        <defs>
          <radialGradient id="kg-graph-bg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#f9fafb" />
            <stop offset="100%" stopColor="#f3f4f6" />
          </radialGradient>
        </defs>
        <rect x="0" y="0" width={size} height={size} fill="url(#kg-graph-bg)" />
        <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
          {allRels.map(renderEdge)}
          {allNodes.map((n) => {
            const c = COLORS[n.kind];
            const r = radiusForImportance(n.importance);
            const isSel = selectedId === n.entity_id;
            return (
              <g
                key={n.entity_id}
                data-node-id={n.entity_id}
                transform={`translate(${n.x}, ${n.y})`}
                onClick={handleNodeClick(n)}
                style={{ cursor: 'pointer' }}
              >
                <circle
                  r={r}
                  fill={c.fill}
                  stroke={isSel ? '#000' : c.stroke}
                  strokeWidth={isSel ? 2.5 : 1.5}
                />
                <text
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize={Math.max(8, r * 0.55)}
                  fill={c.text}
                  style={{ pointerEvents: 'none' }}
                >
                  {n.name.length > 4 ? n.name.slice(0, 3) + '…' : n.name}
                </text>
                {isSel && (
                  <text
                    y={r + 12}
                    fontSize="10"
                    textAnchor="middle"
                    fill="#111827"
                    style={{ pointerEvents: 'none' }}
                  >
                    {n.name}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* 工具条 */}
      <div className="kg-graph-toolbar">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setZoom((z) => Math.min(3, z + 0.2))}
          title="放大"
          aria-label="放大"
        >+</button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setZoom((z) => Math.max(0.4, z - 0.2))}
          title="缩小"
          aria-label="缩小"
        >−</button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={handleDoubleClick}
          title="重置视图"
          aria-label="重置"
        >⟲</button>
        <span className="muted small">{(zoom * 100).toFixed(0)}%</span>
      </div>

      {/* 选中节点详情面板 */}
      {selected && (
        <div className="kg-graph-detail">
          <div className="kg-graph-detail-head">
            <span className={`kg-graph-kind-tag kind-${selected.kind}`}>
              {selected.kind === 'character' ? '人物' : selected.kind === 'event' ? '事件' : '地点'}
            </span>
            <strong>{selected.name}</strong>
            <button
              type="button"
              className="icon-btn"
              onClick={() => setSelectedId(null)}
              title="关闭"
              aria-label="关闭详情"
              style={{ marginLeft: 'auto' }}
            >×</button>
          </div>
          <div className="kg-graph-detail-body">
            {selected.role && <div><span className="muted">角色</span>: {selected.role}</div>}
            {selected.faction && <div><span className="muted">势力</span>: {selected.faction}</div>}
            {selected.status && <div><span className="muted">状态</span>: {selected.status}</div>}
            {selected.in_story_time && <div><span className="muted">时间</span>: {selected.in_story_time}</div>}
            {selected.location_type && <div><span className="muted">类型</span>: {selected.location_type}</div>}
            {selected.importance != null && (
              <div><span className="muted">权重</span>: {'★'.repeat(selected.importance)}{'☆'.repeat(5 - selected.importance)}</div>
            )}
            {selected.attributes && Object.keys(selected.attributes).length > 0 && (
              <details>
                <summary>属性 ({Object.keys(selected.attributes).length})</summary>
                <ul className="kg-graph-attrs">
                  {Object.entries(selected.attributes).map(([k, v]) => (
                    <li key={k}><strong>{k}</strong>: {String(v)}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
