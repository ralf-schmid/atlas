import Link from "next/link";
import Sparkline from "@/components/Sparkline";
import { getLeaderboard, type Leaderboard, type LeaderboardRow } from "@/lib/api";
import { personaColor } from "@/lib/personaColors";

const currency = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

// F112: the depot-value formatter rounds to whole dollars, which turned a real
// malus of 0,0893 $ into "0 $" — it read as if nothing had been computed at all.
// A slippage malus lives in cents by nature, so it gets its own precision.
const malusCurrency = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const percent = new Intl.NumberFormat("de-DE", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const ratio = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 });

export default async function LeaderboardPage({
  searchParams,
}: {
  searchParams: Promise<{ sort?: string }>;
}) {
  const sort = (await searchParams).sort === "adjusted" ? "adjusted" : "raw";
  const board = await getLeaderboard(sort);

  if (board === null || board.rows.length === 0) {
    return (
      <main className="mx-auto w-full max-w-md p-4">
        <h1 className="text-xl font-semibold">Leaderboard</h1>
        <p className="mt-4 text-sm text-gray-600">Noch keine Wettbewerbsdaten vorhanden.</p>
      </main>
    );
  }

  const startLabel = new Intl.DateTimeFormat("de-DE").format(
    new Date(`${board.start}T00:00:00`),
  );

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      <header>
        <h1 className="text-xl font-semibold">Leaderboard</h1>
        <p className="mt-1 text-sm text-gray-600">
          Seit {startLabel} · {board.trading_days} Handelstage · Start{" "}
          {currency.format(board.start_capital)}
        </p>
      </header>

      <SortToggle sort={board.sort} />

      {!board.has_reviews && sort === "adjusted" && (
        <p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
          Noch keine Reviews mit Slippage-Malus — die adjustierte Rendite entspricht
          derzeit der Roh-Rendite.
        </p>
      )}

      <ol className="flex flex-col gap-3">
        {board.rows.map((row) => (
          <li key={row.persona}>
            <Row row={row} sort={board.sort} startCapital={board.start_capital} />
          </li>
        ))}
      </ol>

      {board.benchmark !== null && (
        <section className="rounded-xl border border-dashed border-gray-300 p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">
                {board.benchmark.symbol}-Benchmark
              </p>
              <p className="text-xs text-gray-500">Buy-and-hold</p>
            </div>
            <Sparkline
              values={board.benchmark.sparkline}
              baseline={board.start_capital}
              color="#6b7280"
            />
            <div className="shrink-0 text-right">
              <p className={returnClass(board.benchmark.raw_return)}>
                {percent.format(board.benchmark.raw_return)}
              </p>
              <p className="text-xs text-gray-500">
                {currency.format(board.benchmark.total_value)}
              </p>
            </div>
          </div>
        </section>
      )}

      <p className="text-xs text-gray-500">
        8 Wochen entsprechen rund 40 Handelstagen — statistisch zu wenig, um Können
        von Zufall zu trennen (ARCHITECTURE.md §4.7). Die Rangfolge ist ein
        Zwischenstand, kein Beweis.
      </p>
    </main>
  );
}

function SortToggle({ sort }: { sort: "raw" | "adjusted" }) {
  // min-w-0: without it a flex item never shrinks below its text width and the
  // long "Slippage-adjustiert" label pushes the page into horizontal scroll at 390 px.
  const base =
    "flex min-h-[44px] min-w-0 flex-1 items-center justify-center rounded-lg border px-2 text-center text-[13px] leading-tight";
  const active = "border-gray-900 bg-gray-900 font-medium text-white";
  const inactive = "border-gray-300 text-gray-700";

  return (
    <div className="flex gap-2" role="group" aria-label="Bewertungsmaßstab">
      <Link
        href="/leaderboard?sort=raw"
        className={`${base} ${sort === "raw" ? active : inactive}`}
        aria-current={sort === "raw"}
      >
        Roh
      </Link>
      <Link
        href="/leaderboard?sort=adjusted"
        className={`${base} ${sort === "adjusted" ? active : inactive}`}
        aria-current={sort === "adjusted"}
      >
        Slippage-adjustiert
      </Link>
    </div>
  );
}

function Row({
  row,
  sort,
  startCapital,
}: {
  row: LeaderboardRow;
  sort: Leaderboard["sort"];
  startCapital: number;
}) {
  const value = sort === "adjusted" ? row.adjusted_return : row.raw_return;

  return (
    <Link
      href={`/personas/${row.persona}`}
      className="flex flex-col gap-3 rounded-xl border border-gray-200 p-4 shadow-sm"
    >
      <div className="flex items-center gap-2">
        <span className="w-4 shrink-0 text-sm font-semibold text-gray-400">{row.rank}</span>
        <span
          aria-hidden
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: personaColor(row.persona) }}
        />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{row.persona}</span>
        <Sparkline
          values={row.sparkline}
          baseline={startCapital}
          color={personaColor(row.persona)}
        />
        <div className="shrink-0 text-right">
          <p className={returnClass(value)}>{percent.format(value)}</p>
          <p className="text-xs text-gray-500">{currency.format(row.total_value)}</p>
        </div>
      </div>

      <dl className="grid grid-cols-4 gap-2 text-center text-[11px] text-gray-500">
        <div>
          <dt>Trades</dt>
          <dd className="font-medium text-gray-800">{row.trade_count}</dd>
        </div>
        <div>
          <dt>Offen</dt>
          <dd className="font-medium text-gray-800">{row.open_positions}</dd>
        </div>
        <div>
          <dt>Drawdown</dt>
          <dd className="font-medium text-gray-800">
            {(row.max_drawdown * 100).toFixed(1)} %
          </dd>
        </div>
        <div>
          <dt>Sortino</dt>
          <dd className="font-medium text-gray-800">
            {row.sortino === null ? "–" : ratio.format(row.sortino)}
          </dd>
        </div>
      </dl>

      {sort === "adjusted" && row.slippage_malus_usd !== null && (
        <p className="text-[11px] text-gray-500">
          Slippage-Malus: {malusCurrency.format(row.slippage_malus_usd)} aus{" "}
          {row.malus_trade_count} von {row.trade_count} Trades (roh{" "}
          {percent.format(row.raw_return)})
        </p>
      )}
    </Link>
  );
}

function returnClass(value: number): string {
  const tone = value > 0 ? "text-green-700" : value < 0 ? "text-red-700" : "text-gray-700";
  return `text-base font-semibold ${tone}`;
}
