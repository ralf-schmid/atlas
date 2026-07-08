import { getPersonaSnapshot, type PortfolioSnapshot } from "@/lib/api";

// All 6 personas side by side. No ranking/sorting logic here — that belongs to
// the later-phase Leaderboard view (CLAUDE.md); this just lists every persona's
// current snapshot instead of hardcoding a single one (F007's original scope).
const PERSONAS = ["VULTURE", "HYPE", "GUARDIAN", "CHARTIST", "CONTRA", "CRYPTOR"];

const currency = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
});

export default async function Home() {
  const snapshots = await Promise.all(
    PERSONAS.map(async (persona) => ({
      persona,
      snapshot: await getPersonaSnapshot(persona),
    })),
  );

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col gap-6 p-4">
      {snapshots.map(({ persona, snapshot }) => (
        <PersonaCard key={persona} persona={persona} snapshot={snapshot} />
      ))}
    </main>
  );
}

function PersonaCard({
  persona,
  snapshot,
}: {
  persona: string;
  snapshot: PortfolioSnapshot | null;
}) {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{persona}</h1>

      {snapshot === null ? (
        <p className="rounded-lg bg-gray-100 p-4 text-sm text-gray-600">
          Noch kein Snapshot für {persona} vorhanden.
        </p>
      ) : (
        <>
          <section
            aria-label="Depotübersicht"
            className="rounded-xl border border-gray-200 p-4 shadow-sm"
          >
            <dl className="grid grid-cols-2 gap-y-3 text-sm">
              <dt className="text-gray-500">Depotwert</dt>
              <dd className="text-right font-medium">
                {currency.format(snapshot.total_value)}
              </dd>

              <dt className="text-gray-500">Cash</dt>
              <dd className="text-right font-medium">
                {currency.format(snapshot.cash)}
              </dd>

              <dt className="text-gray-500">P&amp;L realisiert</dt>
              <dd
                className={`text-right font-medium ${snapshot.pnl_realized >= 0 ? "text-green-700" : "text-red-700"}`}
              >
                {currency.format(snapshot.pnl_realized)}
              </dd>

              <dt className="text-gray-500">P&amp;L unrealisiert</dt>
              <dd
                className={`text-right font-medium ${snapshot.pnl_unrealized >= 0 ? "text-green-700" : "text-red-700"}`}
              >
                {currency.format(snapshot.pnl_unrealized)}
              </dd>
            </dl>
          </section>

          <section aria-label="Offene Positionen" className="flex flex-col gap-2">
            <h2 className="text-sm font-medium text-gray-500">
              Offene Positionen ({snapshot.positions.length})
            </h2>
            {snapshot.positions.length === 0 ? (
              <p className="text-sm text-gray-500">Keine offenen Positionen.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {snapshot.positions.map((position) => (
                  <li
                    key={position.instrument}
                    className="flex min-h-11 items-center justify-between rounded-lg border border-gray-200 px-4 py-2"
                  >
                    <div>
                      <p className="font-medium">{position.instrument}</p>
                      <p className="text-xs text-gray-500">
                        {position.qty} Stk. @ {currency.format(position.avg_price)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-medium">
                        {currency.format(position.market_value)}
                      </p>
                      <p
                        className={`text-xs ${position.pnl_unrealized >= 0 ? "text-green-700" : "text-red-700"}`}
                      >
                        {currency.format(position.pnl_unrealized)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
