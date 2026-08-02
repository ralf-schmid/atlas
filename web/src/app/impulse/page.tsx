import Link from "next/link";
import { getImpulses } from "@/lib/api";
import { sourceTypeLabel } from "@/lib/labels";

const dateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "short",
  timeStyle: "short",
});

export default async function ImpulseListPage() {
  const impulses = await getImpulses();

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      <header>
        <h1 className="text-xl font-semibold">Impuls-Vergleich</h1>
        <p className="mt-1 text-sm text-gray-600">
          Ein Research-Item, sechs Sichten: was jede Persona daraus gemacht hat — und
          wer es ignoriert hat.
        </p>
      </header>

      {impulses.length === 0 ? (
        <p className="rounded-lg bg-gray-50 p-4 text-sm text-gray-600">
          Noch kein Impuls von einer Persona zitiert.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {impulses.map((impulse) => (
            <li key={impulse.id}>
              <Link
                href={`/impulse/${impulse.id}`}
                className="flex flex-col gap-1 rounded-xl border border-gray-200 p-4 shadow-sm"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate text-sm font-semibold">
                    {sourceTypeLabel(impulse.source_type)}
                  </span>
                  <span className="shrink-0 text-xs text-gray-500">
                    {impulse.citing_personas}/6 zitiert
                  </span>
                </div>
                <p className="text-xs text-gray-500">
                  {dateTime.format(new Date(impulse.cycle_ts))}
                  {impulse.instruments.length > 0 &&
                    ` · ${impulse.instruments.join(", ")}`}
                </p>
                <p className="line-clamp-2 text-sm text-gray-700">{impulse.summary}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
