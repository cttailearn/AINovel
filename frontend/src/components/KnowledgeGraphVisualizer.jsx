import { useEffect, useMemo, useRef, useState } from 'react';

/**
 * Lightweight SVG-based force-directed graph viewer.
 *
 * Renders characters + events as nodes and all relations as edges.
 * Supports pan/zoom, drag, and node selection. Clicking a node invokes
 * the `onSelectNode` callback so the parent can open a detail modal.
 */
const RELATION_STYLE = {
  PARTICIPATES_IN: { color: '#6366f1', label: '参与' },
  包含: { color: '#22c55e', label: '包含' },
  导致: { color: '#ef4444', label: '导致' },
  关联: { color: '#94a3b8', label: '关联' },
};

function relationColor(rel) {
  if (!rel) return RELATION_STYLE.关联.color;
  return RELATION_STYLE[rel]?.color || '#94a3b8';
}

function buildGraph(data) {
  const nodes = [];
  const seen = new Set();
  const pushNode = (n) => {
    if (!n || !n.entity_id || seen.has(n.entity_id)) return;
    seen.add(n.entity_id);
    nodes.push(n);
  };
  (data.characters || []).forEach((c) =>
    pushNode({
      entity_id: c.entity_id,
      name: c.name,
      type: 'character',
      attributes: c.attributes || {},
    })
  );
  (data.events || []).forEach((e) =>
    pushNode({
      entity_id: e.entity_id,
      name: e.name,
      type: 'event',
      attributes: e.attributes || {},
    })
  );

  const edges = [];
  const seenEdge = new Set();
  const pushEdge = (rel) => {
    if (!rel || !rel.source || !rel.target) return;
    const key = `${rel.source}__${rel.relation}__${rel.target}`;
    if (seenEdge.has(key)) return;
    seenEdge.add(key);
    edges.push(rel);
  };
  (data.character_event_relations || []).forEach(pushEdge);
  (data.character_relations || []).forEach(pushEdge);
  (data.event_relations || []).forEach(pushEdge);
  return { nodes, edges };
}

const NODE_RADIUS = {
  character: 22,
  event: 18,
};

const NODE_COLOR = {
  character: '#6366f1',
  event: '#f59e0b',
};

function initialLayout(nodes, width, height) {
  const cx = width / 2;
  const cy = height / 2;
  const n = Math.max(1, nodes.length);
  const radius = Math.min(width, height) * 0.35;
  return nodes.map((node, i) => {
    const angle = (i / n) * Math.PI * 2;
    return {
      ...node,
      x: cx + Math.cos(angle) * radius + (Math.random() - 0.5) * 20,
      y: cy + Math.sin(angle) * radius + (Math.random() - 0.5) * 20,
      vx: 0,
      vy: 0,
    };
  });
}

function stepSimulation(state, opts) {
  const { width, height, alpha, dragNode, dragOffset } = state;
  const { repulsion = 1800, spring = 0.04, springLength = 90, gravity = 0.02, damping = 0.82 } = opts;
  const nodes = state.nodes;
  const edges = state.edges;
  const idx = new Map();
  nodes.forEach((n, i) => idx.set(n.entity_id, i));

  // Repulsion
  for (let i = 0; i < nodes.length; i += 1) {
    const a = nodes[i];
    for (let j = i + 1; j < nodes.length; j += 1) {
      const b = nodes[j];
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let dist2 = dx * dx + dy * dy;
      if (dist2 < 1) {
        dx = (Math.random() - 0.5) * 2;
        dy = (Math.random() - 0.5) * 2;
        dist2 = 4;
      }
      const dist = Math.sqrt(dist2);
      const force = (repulsion * alpha) / dist2;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }
  }

  // Spring (edges)
  for (const e of edges) {
    const i = idx.get(e.source);
    const j = idx.get(e.target);
    if (i === undefined || j === undefined) continue;
    const a = nodes[i];
    const b = nodes[j];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const diff = dist - springLength;
    const fx = (dx / dist) * diff * spring * alpha;
    const fy = (dy / dist) * diff * spring * alpha;
    a.vx += fx;
    a.vy += fy;
    b.vx -= fx;
    b.vy -= fy;
  }

  // Gravity toward center
  const cx = width / 2;
  const cy = height / 2;
  for (const n of nodes) {
    n.vx += (cx - n.x) * gravity * alpha;
    n.vy += (cy - n.y) * gravity * alpha;
  }

  // Integrate
  for (const n of nodes) {
    if (n === dragNode) {
      n.x = dragOffset.x;
      n.y = dragOffset.y;
      n.vx = 0;
      n.vy = 0;
      continue;
    }
    n.vx *= damping;
    n.vy *= damping;
    n.x += n.vx;
    n.y += n.vy;
    // Soft walls
    const r = NODE_RADIUS[n.type] || 18;
    if (n.x < r) { n.x = r; n.vx *= -0.4; }
    if (n.y < r) { n.y = r; n.vy *= -0.4; }
    if (n.x > width - r) { n.x = width - r; n.vx *= -0.4; }
    if (n.y > height - r) { n.y = height - r; n.vy *= -0.4; }
  }
  return nodes;
}

export function KnowledgeGraphVisualizer({
  data,
  onSelectNode,
  onSelectEdge,
  highlightedNodeId,
  height = 520,
  className = '',
}) {
  const wrapperRef = useRef(null);
  const [size, setSize] = useState({ width: 800, height });
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [hoverNode, setHoverNode] = useState(null);
  const [hoverEdge, setHoverEdge] = useState(null);
  const dragRef = useRef(null);
  const panRef = useRef(null);
  const simStateRef = useRef({ nodes: [], edges: [], alpha: 1 });
  const [tick, setTick] = useState(0);
  const animRef = useRef(null);

  const { nodes, edges } = useMemo(() => buildGraph(data || {}), [data]);

  // Observe wrapper size
  useEffect(() => {
    if (!wrapperRef.current) return undefined;
    const el = wrapperRef.current;
    const ro = new ResizeObserver(() => {
      const rect = el.getBoundingClientRect();
      setSize({
        width: Math.max(320, rect.width),
        height,
      });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);

  // Initialize / update simulation state when graph data changes
  useEffect(() => {
    const { width, height: h } = size;
    // Preserve positions of existing nodes
    const prev = new Map(
      simStateRef.current.nodes.map((n) => [n.entity_id, n])
    );
    const next = nodes.map((n) => {
      const old = prev.get(n.entity_id);
      if (old) {
        return {
          ...n,
          x: old.x,
          y: old.y,
          vx: old.vx,
          vy: old.vy,
        };
      }
      // Place new node near center with a tiny offset
      const angle = Math.random() * Math.PI * 2;
      const radius = 40 + Math.random() * 60;
      return {
        ...n,
        x: width / 2 + Math.cos(angle) * radius,
        y: h / 2 + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
      };
    });
    simStateRef.current = {
      nodes: next,
      edges,
      alpha: 1,
      width,
      height: h,
      dragNode: null,
      dragOffset: { x: 0, y: 0 },
    };
    setTick((t) => t + 1);
  }, [nodes, edges, size.width, size.height]);

  // Animation loop
  useEffect(() => {
    let alpha = 1;
    let cooling = false;
    const animate = () => {
      const state = simStateRef.current;
      if (state.alpha > 0.05 || cooling) {
        stepSimulation(state, {});
        state.alpha *= 0.985;
        if (state.alpha < 0.05) cooling = false;
        setTick((t) => t + 1);
        animRef.current = requestAnimationFrame(animate);
      } else {
        animRef.current = null;
      }
    };
    // (Re)start the simulation when alpha resets due to data updates.
    simStateRef.current.alpha = 1;
    if (!animRef.current) {
      animRef.current = requestAnimationFrame(animate);
    }
    return () => {
      if (animRef.current) {
        cancelAnimationFrame(animRef.current);
        animRef.current = null;
      }
    };
  }, [nodes, edges, size.width, size.height]);

  const screenToWorld = (sx, sy) => {
    const { x, y, k } = transform;
    return { x: (sx - x) / k, y: (sy - y) / k };
  };

  const handlePointerDown = (e) => {
    if (e.button !== 0) return;
    const target = e.target;
    const nodeId = target?.dataset?.nodeId;
    if (nodeId) {
      const state = simStateRef.current;
      const node = state.nodes.find((n) => n.entity_id === nodeId);
      if (node) {
        const rect = wrapperRef.current.getBoundingClientRect();
        const world = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
        state.dragNode = node;
        state.dragOffset = { x: world.x, y: world.y };
        state.alpha = Math.max(state.alpha, 0.3);
        dragRef.current = { nodeId, rect };
        e.preventDefault();
        return;
      }
    }
    // Pan
    panRef.current = { startX: e.clientX, startY: e.clientY, baseX: transform.x, baseY: transform.y };
  };

  const handlePointerMove = (e) => {
    if (dragRef.current) {
      const state = simStateRef.current;
      const rect = wrapperRef.current.getBoundingClientRect();
      const world = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
      state.dragOffset = world;
      setTick((t) => t + 1);
      e.preventDefault();
      return;
    }
    if (panRef.current) {
      const dx = e.clientX - panRef.current.startX;
      const dy = e.clientY - panRef.current.startY;
      setTransform((t) => ({ ...t, x: panRef.current.baseX + dx, y: panRef.current.baseY + dy }));
    }
  };

  const handlePointerUp = () => {
    if (dragRef.current) {
      const state = simStateRef.current;
      state.dragNode = null;
      dragRef.current = null;
    }
    panRef.current = null;
  };

  const handleWheel = (e) => {
    e.preventDefault();
    const rect = wrapperRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const delta = -e.deltaY * 0.0015;
    setTransform((t) => {
      const newK = Math.max(0.3, Math.min(3, t.k * (1 + delta)));
      const ratio = newK / t.k;
      return {
        k: newK,
        x: mx - (mx - t.x) * ratio,
        y: my - (my - t.y) * ratio,
      };
    });
  };

  const handleNodeClick = (node) => {
    onSelectNode?.(node);
  };

  const resetView = () => {
    setTransform({ x: 0, y: 0, k: 1 });
    simStateRef.current.alpha = 1;
    if (!animRef.current) {
      animRef.current = requestAnimationFrame(() => {
        const animate = () => {
          const state = simStateRef.current;
          if (state.alpha > 0.05) {
            stepSimulation(state, {});
            state.alpha *= 0.97;
            setTick((t) => t + 1);
            animRef.current = requestAnimationFrame(animate);
          } else {
            animRef.current = null;
          }
        };
        animate();
      });
    }
  };

  const idxMap = useMemo(() => {
    const m = new Map();
    simStateRef.current.nodes.forEach((n, i) => m.set(n.entity_id, i));
    return m;
  }, [tick]);

  const stateNodes = simStateRef.current.nodes;
  const stateEdges = simStateRef.current.edges;

  const empty = stateNodes.length === 0;

  return (
    <div
      ref={wrapperRef}
      className={`kg-graph-wrapper ${className}`}
      style={{ height }}
      onMouseDown={handlePointerDown}
      onMouseMove={handlePointerMove}
      onMouseUp={handlePointerUp}
      onMouseLeave={handlePointerUp}
      onWheel={handleWheel}
    >
      <div className="kg-graph-toolbar">
        <span className="kg-graph-hint">
          拖动节点 / 滚轮缩放 / 空白处拖动平移
        </span>
        <div className="kg-graph-legend">
          <span className="kg-legend-item">
            <span className="kg-legend-dot" style={{ background: NODE_COLOR.character }} />
            人物
          </span>
          <span className="kg-legend-item">
            <span className="kg-legend-dot" style={{ background: NODE_COLOR.event }} />
            事件
          </span>
          <span className="kg-legend-item">
            <span className="kg-legend-line" style={{ background: '#6366f1' }} />
            参与
          </span>
          <span className="kg-legend-item">
            <span className="kg-legend-line" style={{ background: '#22c55e' }} />
            包含
          </span>
          <span className="kg-legend-item">
            <span className="kg-legend-line" style={{ background: '#ef4444' }} />
            导致
          </span>
        </div>
        <button type="button" className="kg-graph-reset" onClick={resetView}>
          复位
        </button>
      </div>
      {empty ? (
        <div className="kg-graph-empty">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
            <circle cx="4" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
            <circle cx="20" cy="6" r="2" stroke="currentColor" strokeWidth="2" />
            <circle cx="4" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
            <circle cx="20" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
            <path d="M6 6l4 4M18 6l-4 4M6 18l4-4M18 18l-4-4" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <p>暂无图谱数据，先构建知识图谱后即可在此查看</p>
        </div>
      ) : (
        <svg
          className="kg-graph-svg"
          width={size.width}
          height={size.height}
          viewBox={`0 0 ${size.width} ${size.height}`}
        >
          <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
            {/* Edges */}
            {stateEdges.map((e, i) => {
              const si = idxMap.get(e.source);
              const ti = idxMap.get(e.target);
              if (si === undefined || ti === undefined) return null;
              const a = stateNodes[si];
              const b = stateNodes[ti];
              const color = relationColor(e.relation);
              const isHighlighted =
                hoverEdge === i ||
                (hoverNode && (hoverNode.entity_id === e.source || hoverNode.entity_id === e.target)) ||
                (highlightedNodeId && (highlightedNodeId === e.source || highlightedNodeId === e.target));
              const strokeWidth = isHighlighted ? 2.4 : 1.2;
              const opacity = hoverNode || hoverEdge || highlightedNodeId
                ? (isHighlighted ? 1 : 0.25)
                : 0.75;
              const mx = (a.x + b.x) / 2;
              const my = (a.y + b.y) / 2;
              return (
                <g key={`e-${i}`} opacity={opacity} style={{ cursor: 'pointer' }}
                  onMouseEnter={() => setHoverEdge(i)}
                  onMouseLeave={() => setHoverEdge(null)}
                  onClick={(ev) => { ev.stopPropagation(); onSelectEdge?.(e); }}
                >
                  <line
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke={color}
                    strokeWidth={strokeWidth}
                    strokeLinecap="round"
                  />
                  {(hoverEdge === i || isHighlighted) && (
                    <text
                      x={mx}
                      y={my - 4}
                      fill={color}
                      fontSize={11}
                      textAnchor="middle"
                      className="kg-edge-label"
                    >
                      {RELATION_STYLE[e.relation]?.label || e.relation}
                    </text>
                  )}
                </g>
              );
            })}
            {/* Nodes */}
            {stateNodes.map((n) => {
              const r = NODE_RADIUS[n.type] || 18;
              const color = NODE_COLOR[n.type] || '#6366f1';
              const isHover = hoverNode && hoverNode.entity_id === n.entity_id;
              const isFocus = highlightedNodeId === n.entity_id;
              const dim = hoverNode || highlightedNodeId
                ? (isHover || isFocus ? 1 : 0.35)
                : 1;
              return (
                <g
                  key={n.entity_id}
                  data-node-id={n.entity_id}
                  transform={`translate(${n.x},${n.y})`}
                  opacity={dim}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={() => setHoverNode(n)}
                  onMouseLeave={() => setHoverNode(null)}
                  onClick={(ev) => { ev.stopPropagation(); handleNodeClick(n); }}
                >
                  {(isHover || isFocus) && (
                    <circle r={r + 6} fill={color} opacity={0.18} />
                  )}
                  <circle r={r} fill={color} stroke="#0f172a" strokeWidth={2} />
                  <text
                    y={r + 14}
                    textAnchor="middle"
                    fontSize={12}
                    className="kg-node-label"
                    fill="currentColor"
                  >
                    {n.name}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      )}
    </div>
  );
}
