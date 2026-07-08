import Link from "next/link";
import {
  getPersonaProfile,
  getPersonaSnapshot,
  type PersonaProfile,
  type PortfolioSnapshot,
} from "@/lib/api";

// All 6 personas side by side. No ranking/sorting logic here — that belongs to
// the later-phase Leaderboard view (CLAUDE.md); this just lists every persona's
// current snapshot instead of hardcoding a single one (F007's original scope).
const PERSONAS = ["VULTURE", "HYPE", "GUARDIAN", "CHARTIST", "CONTRA", "CRYPTOR"];

const currency = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
});

export default async function Home() {
  const cards = await Promise.all(
    PERSONAS.map(async (persona) => ({
      persona,
      profile: await getPersonaProfile(persona),
      snapshot: await getPersonaSnapshot(persona),
    })),
  );

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col gap-6 p-4">
      {cards.map(({ persona, profile, snapshot }) => (
        <PersonaCard
          key={persona}
          persona={persona}
          profile={profile}
          snapshot={snapshot}
        />
      ))}
    </main>
  );
}

function PersonaCard({
  persona,
  profile,
  snapshot,
}: {
  persona: string;
  profile: PersonaProfile | null;
  snapshot: PortfolioSnapshot | null;
}) {
  return (
    <Link href={`/personas/${persona}`} className="flex flex-col gap-3">
      <div>
        <h1 className="text-xl font-semibold">
          {profile?.display_name ?? persona}
        </h1>
        {profile !== null && (
          <p className="mt-1 text-sm text-gray-600">{profile.philosophy}</p>
        )}
      </div>

      {snapshot === null ? (
        <p className="rounded-lg bg-gray-100 p-4 text-sm text-gray-600">
          Noch kein Snapshot für {persona} vorhanden.
        </p>
      ) : (
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
      )}
    </Link>
  );
}
