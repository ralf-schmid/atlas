import type { HoldingChart } from "@/lib/api";

const VIEW_WIDTH = 320;
const VIEW_HEIGHT = 120;
const PADDING_X = 8;
const PADDING_TOP = 12;
const PADDING_BOTTOM = 20;

const dateLabel = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
});

const priceLabel = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
});

interface Point {
  x: number;
  y: number;
  ts: string;
}

function buildPoints(chart: HoldingChart, minPrice: number, maxPrice: number): Point[] {
  const series = [
    ...chart.bars.map((bar) => ({ ts: bar.ts, price: bar.close })),
    ...(chart.live_price
      ? [{ ts: chart.live_price.ts, price: chart.live_price.price }]
      : []),
  ];
  const lastIndex = Math.max(series.length - 1, 1);
  const plotWidth = VIEW_WIDTH - PADDING_X * 2;
  const plotHeight = VIEW_HEIGHT - PADDING_TOP - PADDING_BOTTOM;
  const priceRange = maxPrice - minPrice || 1;

  return series.map((point, i) => ({
    ts: point.ts,
    x: PADDING_X + (i / lastIndex) * plotWidth,
    y: PADDING_TOP + (1 - (point.price - minPrice) / priceRange) * plotHeight,
  }));
}

function nearestBarIndex(chart: HoldingChart, fillTs: string): number {
  const fillDate = fillTs.slice(0, 10);
  let closest = 0;
  let closestDiff = Infinity;
  chart.bars.forEach((bar, i) => {
    const diff = Math.abs(new Date(bar.ts).getTime() - new Date(fillDate).getTime());
    if (diff < closestDiff) {
      closestDiff = diff;
      closest = i;
    }
  });
  return closest;
}

export default function PriceChart({ chart }: { chart: HoldingChart }) {
  if (chart.bars.length === 0) {
    return (
      <p className="mt-2 text-xs text-gray-400">
        Keine Kursdaten verfügbar.
      </p>
    );
  }

  const prices = [
    ...chart.bars.map((bar) => bar.close),
    ...chart.fills.map((fill) => fill.price),
    ...(chart.live_price ? [chart.live_price.price] : []),
  ];
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);

  const points = buildPoints(chart, minPrice, maxPrice);
  const barPoints = chart.live_price ? points.slice(0, -1) : points;
  const livePoint = chart.live_price ? points[points.length - 1] : null;

  const linePath = `M ${points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" L ")}`;

  return (
    <div className="mt-2">
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="w-full"
        role="img"
        aria-label={`Kursverlauf ${chart.instrument} seit ${chart.start}`}
      >
        <path d={linePath} fill="none" stroke="#4b5563" strokeWidth="1.5" />

        {chart.fills.map((fill, i) => {
          const barIndex = nearestBarIndex(chart, fill.ts);
          const p = barPoints[barIndex] ?? barPoints[barPoints.length - 1];
          const isBuy = fill.action === "buy";
          return (
            <polygon
              key={i}
              points={
                isBuy
                  ? `${p.x - 4},${p.y + 4} ${p.x + 4},${p.y + 4} ${p.x},${p.y - 4}`
                  : `${p.x - 4},${p.y - 4} ${p.x + 4},${p.y - 4} ${p.x},${p.y + 4}`
              }
              fill={isBuy ? "#15803d" : "#b91c1c"}
            >
              <title>
                {isBuy ? "Kauf" : "Verkauf"} {fill.qty} @ {priceLabel.format(fill.price)} (
                {fill.ts.slice(0, 10)})
              </title>
            </polygon>
          );
        })}

        {livePoint && (
          <circle cx={livePoint.x} cy={livePoint.y} r={3.5} fill="#1d4ed8">
            <title>
              Live: {priceLabel.format(chart.live_price!.price)}
            </title>
          </circle>
        )}

        <text x={PADDING_X} y={VIEW_HEIGHT - 4} className="fill-gray-400 text-[9px]">
          {dateLabel.format(new Date(chart.bars[0].ts))}
        </text>
        <text
          x={VIEW_WIDTH - PADDING_X}
          y={VIEW_HEIGHT - 4}
          textAnchor="end"
          className="fill-gray-400 text-[9px]"
        >
          {livePoint ? "live" : dateLabel.format(new Date(chart.bars[chart.bars.length - 1].ts))}
        </text>
        <text x={PADDING_X} y={10} className="fill-gray-400 text-[9px]">
          {priceLabel.format(maxPrice)}
        </text>
        <text
          x={PADDING_X}
          y={VIEW_HEIGHT - PADDING_BOTTOM + 8}
          className="fill-gray-400 text-[9px]"
        >
          {priceLabel.format(minPrice)}
        </text>
      </svg>
    </div>
  );
}
