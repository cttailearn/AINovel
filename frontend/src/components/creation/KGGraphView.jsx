// ⑩ 知识图谱简易可视化 — 纯 SVG, 同心圆布局
// 内圈: 人物 (按 importance 分层); 中圈: 事件; 外圈: 地点
// 节点大小 ∝ importance, 颜色按类型 (人物=蓝, 事件=橙, 地点=绿)
import { useMemo } from 'react';

const COLORS = {
  character: { fill: '#dbeafe', stroke: '#3b82f6', text: '#1e3a8a' },
  event:     { fill: '#fed7aa', stroke: '#f97316', text: '#7c2d12' },
  location:  { fill: '#d1fae5', stroke: '#10b981', text: '#064e3b' },
};

const MAX_NODES_PER_RING = 16;

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
}) {
  const layout = useMemo(() => {
    const size = 480;
    const cx = size / 2;
    const cy = size / 2;
    // 按 importance 倒序
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

    return { size, cx, cy, allNodes, byId };
  }, [characters, events, locations]);

  const { size, allNodes, byId } = layout;

  if (allNodes.length === 0) {
    return (
      <p className="muted small" style={{ textAlign: 'center', padding: '24px 0' }}>
        知识图谱暂无实体. 确认章节后会自动抽取.
      </p>
    );
  }

  const allRels = [
    ...characterRelations.map((r) => ({ ...r, type: 'cc' })),
    ...characterEventRelations.map((r) => ({ ...r, type: 'ce' })),
    ...eventRelations.map((r) => ({ ...r, type: 'ee' })),
  ];

  return (
    <div className="kg-graph-wrap">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        className="kg-graph-svg"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <radialGradient id="kg-graph-bg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#f9fafb" />
            <stop offset="100%" stopColor="#f3f4f6" />
          </radialGradient>
        </defs>
        <rect x="0" y="0" width={size} height={size} fill="url(#kg-graph-bg)" />

        {/* 圈层参考线 */}
        <circle cx={size/2} cy={size/2} r="110" fill="none" stroke="#e5e7eb" strokeDasharray="2 4" />
        <circle cx={size/2} cy={size/2} r="180" fill="none" stroke="#e5e7eb" strokeDasharray="2 4" />
        <circle cx={size/2} cy={size/2} r="235" fill="none" stroke="#e5e7eb" strokeDasharray="2 4" />

        {/* 关系连线 */}
        {allRels.map((r, i) => {
          const s = byId[r.source_entity_id];
          const t = byId[r.target_entity_id];
          if (!s || !t) return null;
          return (
            <line
              key={`rel-${i}`}
              x1={s.x} y1={s.y} x2={t.x} y2={t.y}
              stroke="#9ca3af"
              strokeWidth={r.type === 'cc' ? 1.5 : 1}
              strokeDasharray={r.type === 'ee' ? '3 3' : ''}
              opacity={0.55}
            />
          );
        })}

        {/* 节点 */}
        {allNodes.map((n, i) => {
          const c = COLORS[n.kind];
          const r = radiusForImportance(n.importance || n.attributes?.importance || 2);
          const label = n.name?.length > 4
            ? n.name.slice(0, 4) + '…'
            : (n.name || n.entity_id);
          return (
            <g key={`node-${i}`} transform={`translate(${n.x},${n.y})`}>
              <title>{n.name || n.entity_id} ({n.kind})</title>
              <circle r={r} fill={c.fill} stroke={c.stroke} strokeWidth={2} />
              <text
                x="0"
                y="3"
                textAnchor="middle"
                fontSize="9"
                fill={c.text}
                fontWeight="600"
              >
                {label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="kg-graph-legend">
        <span className="kg-graph-legend-item">
          <i style={{ background: COLORS.character.fill, borderColor: COLORS.character.stroke }} />
          人物
        </span>
        <span className="kg-graph-legend-item">
          <i style={{ background: COLORS.event.fill, borderColor: COLORS.event.stroke }} />
          事件
        </span>
        <span className="kg-graph-legend-item">
          <i style={{ background: COLORS.location.fill, borderColor: COLORS.location.stroke }} />
          地点
        </span>
      </div>
    </div>
  );
}
