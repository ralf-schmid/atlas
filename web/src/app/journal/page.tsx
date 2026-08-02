import Link from "next/link";
import DecisionCard from "@/components/DecisionCard";
import { getPersonaDecisions, type DecisionFilter } from "@/lib/api";
import { personaColor } from "@/lib/personaColors";

const PERSONAS = ["VULTURE", "HYPE", "GUARDIAN", "CHARTIST", "CONTRA", "CRYPTOR"];

const FILTERS: { key: DecisionFilter; label: string }[] = [
  { key: "all", label: "Alle" },
  { key: "traded", label: "Gehandelt" },
  { key: "rejected", label: "Verworfen" },
  { key: "hold", label: "Gehalten" },
];

function isFilter(value: string | undefined): value is DecisionFilter {
  return FILTERS.some((entry) => entry.key === value);
}

export default async function JournalPage({
  searchParams,
}: {
  searchParams: Promise<{ persona?: string; filter?: string }>;
}) {
  const params = await searchParams;
  const persona = PERSONAS.includes(params.persona?.toUpperCase() ?? "")
    ? params.persona!.toUpperCase()
    : PERSONAS[0];
  const filter: DecisionFilter = isFilter(params.filter) ? params.filter : "all";
  const decisions = await getPersonaDecisions(persona, filter);

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      <header>
        <h1 className="text-xl font-semibold">Decision Journal</h1>
        <p className="mt-1 text-sm text-gray-600">
          Jede Entscheidung mit These, Quellen, Erwartung und Ausgang — auch die
          verworfenen Ideen.
        </p>
      </header>

      <nav aria-label="Persona" className="flex flex-wrap gap-2">
        {PERSONAS.map((name) => (
          <Link
            key={name}
            href={`/journal?persona=${name}&filter=${filter}`}
            aria-current={name === persona}
            className={`flex min-h-[44px] items-center gap-1.5 rounded-lg border px-3 text-[13px] ${
              name === persona
                ? "border-gray-900 font-medium text-gray-900"
                : "border-gray-300 text-gray-600"
            }`}
          >
            <span
              aria-hidden
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: personaColor(name) }}
            />
            {name}
          </Link>
        ))}
      </nav>

      <nav aria-label="Ausgang" className="flex gap-2">
        {FILTERS.map((entry) => (
          <Link
            key={entry.key}
            href={`/journal?persona=${persona}&filter=${entry.key}`}
            aria-current={entry.key === filter}
            className={`flex min-h-[44px] min-w-0 flex-1 items-center justify-center rounded-lg border px-2 text-center text-[13px] leading-tight ${
              entry.key === filter
                ? "border-gray-900 bg-gray-900 font-medium text-white"
                : "border-gray-300 text-gray-700"
            }`}
          >
            {entry.label}
          </Link>
        ))}
      </nav>

      {decisions.length === 0 ? (
        <p className="rounded-lg bg-gray-50 p-4 text-sm text-gray-600">
          Keine Einträge für diesen Filter.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {decisions.map((decision) => (
            <li key={decision.id}>
              <DecisionCard decision={decision} />
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
