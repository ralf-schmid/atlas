import type { PortfolioHistorySeries } from "@/lib/api";
import { personaColor } from "@/lib/personaColors";

const VIEW_WIDTH = 320;
const VIEW_HEIGHT = 150;
const PADDING_LEFT = 8;
const PADDING_RIGHT = 8;
const PADDING_TOP = 12;
const PADDING_BOTTOM = 20;

const dateLabel = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
});

const valueLabel = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export type HistoryMetric = "total_value" | "position_value";

interface Bounds {
  minTs: number;
  maxTs: number;
  minValue: number;
  maxValue: number;
}

function computeBounds(
  series: PortfolioHistorySeries[],
  metric: HistoryMetric,
  reference: number | null,
): Bounds {
  const timestamps = series.flatMap((s) => s.points.map((p) => new Date(p.ts).getTime()));
  const values = series.flatMap((s) => s.points.map((p) => p[metric]));
  if (reference !== null) {
    values.push(reference);
  }
  // Position value is meaningful only against zero — an all-cash portfolio would
  // otherwise render as a line floating in an invented range.
  if (metric === "position_value") {
    values.push(0);
  }

  return {
    minTs: Math.min(...timestamps),
    maxTs: Math.max(...timestamps),
    minValue: Math.min(...values),
    maxValue: Math.max(...values),
  };
}

function project(ts: string, value: number, bounds: Bounds): { x: number; y: number } {
  const plotWidth = VIEW_WIDTH - PADDING_LEFT - PADDING_RIGHT;
  const plotHeight = VIEW_HEIGHT - PADDING_TOP - PADDING_BOTTOM;
  const tsRange = bounds.maxTs - bounds.minTs || 1;
  const valueRange = bounds.maxValue - bounds.minValue || 1;

  return {
    x: PADDING_LEFT + ((new Date(ts).getTime() - bounds.minTs) / tsRange) * plotWidth,
    y: PADDING_TOP + (1 - (value - bounds.minValue) / valueRange) * plotHeight,
  };
}

export default function PortfolioHistoryChart({
  series,
  metric,
  title,
  subtitle,
  reference = null,
}: {
  series: PortfolioHistorySeries[];
  metric: HistoryMetric;
  title: string;
  subtitle: string;
  reference?: number | null;
}) {
  const withPoints = series.filter((s) => s.points.length > 0);

  if (withPoints.length === 0) {
    return (
      <section className="rounded-xl border border-gray-200 p-4 shadow-sm">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="mt-2 text-xs text-gray-400">Noch keine Snapshots im Wettbewerbszeitraum.</p>
      </section>
    );
  }

  const bounds = computeBounds(withPoints, metric, reference);
  const referenceY = reference === null ? null : project(new Date(bounds.minTs).toISOString(), reference, bounds).y;

  return (
    <section className="rounded-xl border border-gray-200 p-4 shadow-sm">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="mt-1 text-xs text-gray-500">{subtitle}</p>

      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="mt-2 w-full"
        role="img"
        aria-label={`${title} je Persona im Zeitverlauf`}
      >
        {referenceY !== null && (
          <line
            x1={PADDING_LEFT}
            y1={referenceY}
            x2={VIEW_WIDTH - PADDING_RIGHT}
            y2={referenceY}
            stroke="#d1d5db"
            strokeWidth="1"
            strokeDasharray="3 3"
          />
        )}

        {withPoints.map((s) => {
          const points = s.points.map((p) => project(p.ts, p[metric], bounds));
          const path = `M ${points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" L ")}`;
          return (
            <g key={s.persona}>
              <path d={path} fill="none" stroke={personaColor(s.persona)} strokeWidth="1.5" />
              <circle
                cx={points[points.length - 1].x}
                cy={points[points.length - 1].y}
                r={2.5}
                fill={personaColor(s.persona)}
              />
            </g>
          );
        })}

        <text x={PADDING_LEFT} y={10} className="fill-gray-400 text-[9px]">
          {valueLabel.format(bounds.maxValue)}
        </text>
        <text
          x={PADDING_LEFT}
          y={VIEW_HEIGHT - PADDING_BOTTOM + 8}
          className="fill-gray-400 text-[9px]"
        >
          {valueLabel.format(bounds.minValue)}
        </text>
        <text x={PADDING_LEFT} y={VIEW_HEIGHT - 4} className="fill-gray-400 text-[9px]">
          {dateLabel.format(new Date(bounds.minTs))}
        </text>
        <text
          x={VIEW_WIDTH - PADDING_RIGHT}
          y={VIEW_HEIGHT - 4}
          textAnchor="end"
          className="fill-gray-400 text-[9px]"
        >
          {dateLabel.format(new Date(bounds.maxTs))}
        </text>
      </svg>

      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {withPoints.map((s) => (
          <li key={s.persona} className="flex items-center gap-1 text-[11px] text-gray-600">
            <span
              aria-hidden
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: personaColor(s.persona) }}
            />
            {s.persona}{" "}
            <span className="text-gray-400">
              {valueLabel.format(s.points[s.points.length - 1][metric])}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
