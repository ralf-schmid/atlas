import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getHoldingChart,
  getPersonaDecisions,
  getPersonaHoldings,
  getPersonaProfile,
  getPersonaTransactions,
  type Holding,
  type HoldingChart,
} from "@/lib/api";
import {
  actionLabel,
  ageDaysLabel,
  decisionStatusLabel,
  orderStatusLabel,
  sourceTypeLabel,
} from "@/lib/labels";
import PriceChart from "@/components/PriceChart";

const currency = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
});

const dateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatDate(value: string | null): string {
  return value === null ? "–" : dateTime.format(new Date(value));
}

async function loadHoldingCharts(
  persona: string,
  holdings: Holding[],
): Promise<Record<string, HoldingChart | null>> {
  const entries = await Promise.all(
    holdings.map(async (holding) => [
      holding.instrument,
      await getHoldingChart(persona, holding.instrument),
    ] as const),
  );
  return Object.fromEntries(entries);
}

function pnlClass(value: number): string {
  return value >= 0 ? "text-green-700" : "text-red-700";
}

export default async function PersonaDetailPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name: persona } = await params;

  const [profile, holdings, transactions, decisions] = await Promise.all([
    getPersonaProfile(persona),
    getPersonaHoldings(persona),
    getPersonaTransactions(persona),
    getPersonaDecisions(persona),
  ]);

  if (profile === null) {
    notFound();
  }

  const charts = await loadHoldingCharts(persona, holdings);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col gap-6 p-4">
      <Link href="/" className="text-sm text-gray-500">
        ← Übersicht
      </Link>

      <header className="flex flex-col gap-3">
        <h1 className="text-xl font-semibold">{profile.display_name}</h1>
        <dl className="flex flex-col gap-3 text-sm">
          <div>
            <dt className="font-medium text-gray-700">Philosophie</dt>
            <dd className="text-gray-600">{profile.philosophy}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Universum</dt>
            <dd className="text-gray-600">{profile.universe}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Signale</dt>
            <dd className="text-gray-600">{profile.signals}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Haltedauer</dt>
            <dd className="text-gray-600">{profile.holding_period}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Erwartete Fehlerart</dt>
            <dd className="text-gray-600">{profile.failure_mode}</dd>
          </div>
        </dl>
      </header>

      <section aria-label="Bestand" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-gray-500">
          Bestand ({holdings.length})
        </h2>
        {holdings.length === 0 ? (
          <p className="text-sm text-gray-500">Keine offenen Positionen.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {holdings.map((holding) => (
              <li
                key={holding.instrument}
                className="rounded-lg border border-gray-200 p-3"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium">{holding.instrument}</p>
                  <p className={`font-medium ${pnlClass(holding.pnl_unrealized)}`}>
                    {currency.format(holding.pnl_unrealized)} (
                    {holding.pnl_unrealized_pct >= 0 ? "+" : ""}
                    {holding.pnl_unrealized_pct.toFixed(1)}%)
                  </p>
                </div>
                <dl className="mt-2 grid grid-cols-2 gap-y-1 text-xs text-gray-600">
                  <dt>Menge</dt>
                  <dd className="text-right">{holding.qty}</dd>
                  <dt>Ø Kaufpreis</dt>
                  <dd className="text-right">
                    {currency.format(holding.avg_price)}
                  </dd>
                  <dt>Aktueller Preis</dt>
                  <dd className="text-right">
                    {currency.format(holding.current_price)}
                  </dd>
                  <dt>Letzter Kauf</dt>
                  <dd className="text-right">
                    {formatDate(holding.last_buy_at)}
                  </dd>
                </dl>
                {charts[holding.instrument] && (
                  <PriceChart chart={charts[holding.instrument]!} />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Transaktionen" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-gray-500">
          Transaktionen ({transactions.length})
        </h2>
        {transactions.length === 0 ? (
          <p className="text-sm text-gray-500">Noch keine Transaktionen.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {transactions.map((tx) => (
              <li
                key={tx.decision_id}
                className="rounded-lg border border-gray-200 p-3 text-sm"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium">
                    {actionLabel(tx.action)} {tx.instrument}
                  </p>
                  <p className="text-xs text-gray-500">
                    {orderStatusLabel(tx.status)}
                  </p>
                </div>
                <p className="text-xs text-gray-500">
                  {formatDate(tx.filled_at ?? tx.submitted_at)}
                  {tx.quantity !== null && ` · ${tx.quantity} Stk.`}
                  {tx.fill_price !== null &&
                    ` @ ${currency.format(tx.fill_price)}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Analyse der Impulse" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-gray-500">
          Analyse der Impulse ({decisions.length})
        </h2>
        {decisions.length === 0 ? (
          <p className="text-sm text-gray-500">Noch keine Entscheidungen.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {decisions.map((decision) => (
              <li
                key={decision.id}
                className="rounded-lg border border-gray-200 p-3 text-sm"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium">
                    {actionLabel(decision.action)} {decision.instrument}
                  </p>
                  <p className="text-xs text-gray-500">
                    {decisionStatusLabel(decision.status)}
                  </p>
                </div>
                <p className="text-xs text-gray-500">
                  {formatDate(decision.ts)}
                  {decision.conviction !== null &&
                    ` · Sicherheit ${(decision.conviction * 100).toFixed(0)}%`}
                </p>
                <p className="mt-2 text-gray-700">{decision.thesis_text}</p>
                {decision.rejection_reason !== null && (
                  <p className="mt-1 text-xs text-gray-500">
                    Ablehnungsgrund: {decision.rejection_reason}
                  </p>
                )}

                {decision.research_items.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-1 border-t border-gray-100 pt-2">
                    {decision.research_items.map((item) => (
                      <li key={item.id} className="text-xs text-gray-600">
                        <span className="font-medium">
                          {sourceTypeLabel(item.source_type)}
                        </span>{" "}
                        · {ageDaysLabel(item.age_days)} — {item.summary}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
