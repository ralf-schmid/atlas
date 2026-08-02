const VIEW_WIDTH = 72;
const VIEW_HEIGHT = 24;
const PADDING = 2;

/** Tiny trend line for a leaderboard row — no axes, no labels, decoration only.
 *  `baseline` (start capital) is drawn as a faint reference so a row that lost
 *  money is recognisable without reading the percentage. */
export default function Sparkline({
  values,
  baseline,
  color,
}: {
  values: number[];
  baseline?: number;
  color: string;
}) {
  if (values.length === 0) {
    return null;
  }

  const scale = [...values, ...(baseline === undefined ? [] : [baseline])];
  const min = Math.min(...scale);
  const max = Math.max(...scale);
  const range = max - min || 1;
  const lastIndex = Math.max(values.length - 1, 1);

  const y = (value: number) =>
    PADDING + (1 - (value - min) / range) * (VIEW_HEIGHT - PADDING * 2);
  const points = values.map((value, index) => ({
    x: PADDING + (index / lastIndex) * (VIEW_WIDTH - PADDING * 2),
    y: y(value),
  }));
  const path =
    values.length === 1
      ? `M ${points[0].x},${points[0].y} L ${VIEW_WIDTH - PADDING},${points[0].y}`
      : `M ${points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" L ")}`;

  return (
    <svg
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      className="h-6 w-[72px] shrink-0"
      aria-hidden
    >
      {baseline !== undefined && (
        <line
          x1={PADDING}
          y1={y(baseline)}
          x2={VIEW_WIDTH - PADDING}
          y2={y(baseline)}
          stroke="#e5e7eb"
          strokeWidth="1"
        />
      )}
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}
