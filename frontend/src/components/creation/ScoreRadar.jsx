// UX-#14: Critic 5 维评分雷达图 (纯 SVG)
// 默认 5 维: 主题一致 / 人物塑造 / 情节推进 / 文笔质量 / 节奏张力
// 数据为空时显示空环; 5 维固定, 允许传入自定义标签
import { useMemo } from 'react';

const DEFAULT_LABELS = ['主题一致', '人物塑造', '情节推进', '文笔质量', '节奏张力'];
const DEFAULT_MAX = 10;

function pt(cx, cy, r, ang) {
  return [cx + Math.cos(ang) * r, cy + Math.sin(ang) * r];
}

export function ScoreRadar({
  scores = {},
  labels = DEFAULT_LABELS,
  max = DEFAULT_MAX,
  size = 200,
}) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 24;

  const angles = useMemo(
    () => labels.map((_, i) => -Math.PI / 2 + (Math.PI * 2 * i) / labels.length),
    [labels]
  );

  // 同心环 (4 圈)
  const rings = [0.25, 0.5, 0.75, 1.0];
  const dataPolygon = angles.map((a, i) => {
    const key = labels[i];
    const v = Number(scores[key] ?? scores[key?.toLowerCase?.()] ?? 0);
    const ratio = Math.max(0, Math.min(1, v / max));
    return pt(cx, cy, radius * ratio, a);
  });

  return (
    <div className="creation-score-radar">
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
        {/* 同心环 */}
        {rings.map((r) => (
          <polygon
            key={r}
            points={angles.map((a) => pt(cx, cy, radius * r, a).join(',')).join(' ')}
            fill="none"
            stroke="var(--border-color, #e5e7eb)"
            strokeWidth="1"
            opacity="0.6"
          />
        ))}
        {/* 坐标轴线 */}
        {angles.map((a, i) => {
          const [x, y] = pt(cx, cy, radius, a);
          return (
            <line
              key={i}
              x1={cx} y1={cy} x2={x} y2={y}
              stroke="var(--border-color, #e5e7eb)"
              strokeWidth="1"
              opacity="0.5"
            />
          );
        })}
        {/* 数据多边形 */}
        {dataPolygon.length > 0 && (
          <polygon
            points={dataPolygon.map((p) => p.join(',')).join(' ')}
            fill="var(--accent-color, #6366f1)"
            fillOpacity="0.25"
            stroke="var(--accent-color, #6366f1)"
            strokeWidth="2"
          />
        )}
        {/* 数据点 */}
        {dataPolygon.map((p, i) => {
          const key = labels[i];
          const v = Number(scores[key] ?? 0);
          return (
            <g key={i}>
              <circle cx={p[0]} cy={p[1]} r="3" fill="var(--accent-color, #6366f1)" />
              <text
                x={p[0]} y={p[1] - 6}
                textAnchor="middle"
                fontSize="10"
                fill="var(--text-primary, #111827)"
              >
                {v > 0 ? v.toFixed(1) : '—'}
              </text>
            </g>
          );
        })}
        {/* 标签 */}
        {angles.map((a, i) => {
          const [x, y] = pt(cx, cy, radius + 14, a);
          return (
            <text
              key={`l-${i}`}
              x={x} y={y}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize="11"
              fill="var(--text-secondary, #6b7280)"
            >
              {labels[i]}
            </text>
          );
        })}
      </svg>
    </div>
  );
}
