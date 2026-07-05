import { getPersonaSnapshot } from "@/lib/api";

// Placeholder: shows one hardcoded persona until a persona-switcher UI exists
// (F007 scope is just "a portfolio snapshot from the DB", not the full
// Leaderboard/persona-navigation from later phases).
const PERSONA = "VULTURE";

const currency = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
});

export default async function Home() {
  const snapshot = await getPersonaSnapshot(PERSONA);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold">{PERSONA}</h1>

      {snapshot === null ? (
        <p className="rounded-lg bg-gray-100 p-4 text-sm text-gray-600">
          Noch kein Snapshot für {PERSONA} vorhanden.
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
    </main>
  );
}
