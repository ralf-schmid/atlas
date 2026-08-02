import Link from "next/link";
import { notFound } from "next/navigation";
import { getCycleTrace } from "@/lib/api";
import { decisionStatusLabel } from "@/lib/labels";
import { personaColor } from "@/lib/personaColors";

const dateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
});

const cost = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

const number = new Intl.NumberFormat("de-DE");

export default async function CycleTracePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const trace = await getCycleTrace(id);

  if (trace === null) {
    notFound();
  }

  const { cycle, runs, hitl_events: hitlEvents } = trace;

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      <Link href="/trace" className="text-sm text-gray-500">
        ← Trace
      </Link>

      <section className="rounded-xl border border-gray-200 p-4 shadow-sm">
        <h1 className="text-sm font-semibold">
          {cycle.market_session} C{cycle.seq}
        </h1>
        <p className="text-xs text-gray-500">
          {dateTime.format(new Date(cycle.started_at))}
        </p>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-[11px] text-gray-500">
          <div>
            <dt>Läufe</dt>
            <dd className="font-medium text-gray-800">
              {cycle.agent_runs}
              {cycle.failed_runs > 0 && (
                <span className="text-amber-700"> ({cycle.failed_runs} ✕)</span>
              )}
            </dd>
          </div>
          <div>
            <dt>Decisions</dt>
            <dd className="font-medium text-gray-800">{cycle.decisions}</dd>
          </div>
          <div>
            <dt>Research</dt>
            <dd className="font-medium text-gray-800">
              {number.format(cycle.research_items)}
            </dd>
          </div>
          <div>
            <dt>Token ein</dt>
            <dd className="font-medium text-gray-800">
              {number.format(cycle.tokens_in)}
            </dd>
          </div>
          <div>
            <dt>Token aus</dt>
            <dd className="font-medium text-gray-800">
              {number.format(cycle.tokens_out)}
            </dd>
          </div>
          <div>
            <dt>Kosten</dt>
            <dd className="font-medium text-gray-800">{cost.format(cycle.cost_usd)}</dd>
          </div>
        </dl>

        {Object.keys(trace.decisions_by_status).length > 0 && (
          <p className="mt-3 border-t border-gray-100 pt-2 text-xs text-gray-600">
            {Object.entries(trace.decisions_by_status)
              .map(([status, count]) => `${count}× ${decisionStatusLabel(status)}`)
              .join(" · ")}
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-gray-500">Läufe ({runs.length})</h2>
        {runs.length === 0 ? (
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            Kein Agent gelaufen. Bei vorhandenem Research heißt das: der Zyklus ist
            gestartet und die Analyse-Schicht kam nie zum Zug.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {runs.map((run, index) => (
              <li
                key={`${run.agent}-${run.persona ?? "shared"}-${index}`}
                className="rounded-lg border border-gray-200 p-3 text-sm"
              >
                <div className="flex items-center gap-2">
                  {run.persona !== null && (
                    <span
                      aria-hidden
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: personaColor(run.persona) }}
                    />
                  )}
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {run.agent}
                    {run.persona !== null && ` · ${run.persona}`}
                  </span>
                  <span
                    className={`shrink-0 text-xs ${
                      run.status === "failed" ? "text-red-700" : "text-gray-500"
                    }`}
                  >
                    {run.status}
                  </span>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  {number.format(run.tokens_in)} / {number.format(run.tokens_out)} Token ·{" "}
                  {cost.format(run.cost_usd)}
                </p>
                {run.error !== null && (
                  <p className="mt-1 rounded bg-red-50 p-2 text-xs text-red-800">
                    {run.error}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-gray-500">
          HITL-Ereignisse ({hitlEvents.length})
        </h2>
        {hitlEvents.length === 0 ? (
          <p className="text-sm text-gray-500">
            Keine — für Paper ist HITL abgeschaltet (config/hitl.yaml).
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {hitlEvents.map((event) => (
              <li
                key={event.decision_id}
                className="rounded-lg border border-gray-200 p-3 text-sm"
              >
                <p className="font-medium">
                  {event.persona} · {event.instrument}
                </p>
                <p className="text-xs text-gray-500">
                  {decisionStatusLabel(event.status)}
                  {event.decided_by !== null && ` · durch ${event.decided_by}`}
                </p>
                <p className="text-xs text-gray-500">
                  Angefragt{" "}
                  {event.requested_at === null
                    ? "–"
                    : dateTime.format(new Date(event.requested_at))}
                  {event.decided_at !== null &&
                    ` · entschieden ${dateTime.format(new Date(event.decided_at))}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
