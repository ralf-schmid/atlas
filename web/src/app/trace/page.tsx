import Link from "next/link";
import { getCycles } from "@/lib/api";

const dateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "short",
  timeStyle: "short",
});

const cost = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

const SESSION_LABELS: Record<string, string> = {
  us_equity: "Aktien",
  crypto: "Krypto",
};

export default async function TraceListPage() {
  const cycles = await getCycles();

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      <header>
        <h1 className="text-xl font-semibold">Agent Trace</h1>
        <p className="mt-1 text-sm text-gray-600">
          Jeder Zyklus mit Läufen, Token, Kosten und Fehlern.
        </p>
      </header>

      {cycles.length === 0 ? (
        <p className="rounded-lg bg-gray-50 p-4 text-sm text-gray-600">
          Noch keine Zyklen gelaufen.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {cycles.map((cycle) => {
            // Research without a single run is the signature of an outage
            // (F101): the cycle started, ingested, and then nothing happened.
            const silent = cycle.research_items > 0 && cycle.agent_runs === 0;
            return (
              <li key={cycle.id}>
                <Link
                  href={`/trace/${cycle.id}`}
                  className={`flex flex-col gap-1 rounded-xl border p-3 shadow-sm ${
                    silent || cycle.failed_runs > 0
                      ? "border-amber-300 bg-amber-50"
                      : "border-gray-200"
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-semibold">
                      {SESSION_LABELS[cycle.market_session] ?? cycle.market_session} C
                      {cycle.seq}
                    </span>
                    <span className="text-xs text-gray-500">
                      {dateTime.format(new Date(cycle.started_at))}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-x-3 text-xs text-gray-600">
                    <span>{cycle.agent_runs} Läufe</span>
                    <span>{cycle.decisions} Decisions</span>
                    <span>{cycle.research_items} Research</span>
                    <span>{cost.format(cycle.cost_usd)}</span>
                  </div>
                  {silent && (
                    <p className="text-xs font-medium text-amber-800">
                      Research da, aber kein Agent gelaufen
                    </p>
                  )}
                  {cycle.failed_runs > 0 && (
                    <p className="text-xs font-medium text-amber-800">
                      {cycle.failed_runs} fehlgeschlagene Läufe
                    </p>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
