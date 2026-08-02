import Link from "next/link";
import { notFound } from "next/navigation";
import { getImpulseComparison, type ImpulseReaction } from "@/lib/api";
import { impulseVerdictLabel, sourceTypeLabel } from "@/lib/labels";
import { personaColor } from "@/lib/personaColors";

const dateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
});

const VERDICT_TONE: Record<ImpulseReaction["verdict"], string> = {
  traded: "bg-green-50 text-green-800",
  rejected: "bg-red-50 text-red-800",
  hold: "bg-gray-100 text-gray-700",
  ignored: "bg-gray-50 text-gray-500",
  no_run: "bg-amber-50 text-amber-800",
};

export default async function ImpulseComparisonPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const comparison = await getImpulseComparison(id);

  if (comparison === null) {
    notFound();
  }

  const { impulse, reactions } = comparison;

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      <Link href="/impulse" className="text-sm text-gray-500">
        ← Impulse
      </Link>

      <section className="rounded-xl border border-gray-200 p-4 shadow-sm">
        <div className="flex items-baseline justify-between gap-2">
          <h1 className="min-w-0 truncate text-sm font-semibold">
            {sourceTypeLabel(impulse.source_type)}
          </h1>
          <span className="shrink-0 text-xs text-gray-500">
            {impulse.citing_personas}/6 zitiert
          </span>
        </div>
        <p className="text-xs text-gray-500">
          Zyklus {dateTime.format(new Date(impulse.cycle_ts))}
          {impulse.instruments.length > 0 && ` · ${impulse.instruments.join(", ")}`}
        </p>
        <p className="mt-2 text-sm text-gray-700">{impulse.summary}</p>
        {comparison.url !== null && (
          <a
            href={comparison.url}
            rel="noreferrer noopener"
            className="mt-2 inline-block text-xs text-gray-500 underline"
          >
            Quelle öffnen
          </a>
        )}
      </section>

      <ul className="flex flex-col gap-3">
        {reactions.map((reaction) => (
          <li
            key={reaction.persona}
            className="rounded-xl border border-gray-200 p-4 text-sm shadow-sm"
          >
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: personaColor(reaction.persona) }}
              />
              <span className="min-w-0 flex-1 truncate font-semibold">
                {reaction.persona}
              </span>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${VERDICT_TONE[reaction.verdict]}`}
              >
                {impulseVerdictLabel(reaction.verdict)}
                {reaction.instrument !== null && ` · ${reaction.instrument}`}
              </span>
            </div>

            {reaction.thesis_text !== null && (
              <p className="mt-2 text-gray-700">{reaction.thesis_text}</p>
            )}
            {reaction.rejection_reason !== null && (
              <p className="mt-2 rounded-lg bg-gray-50 p-2 text-xs text-gray-600">
                <span className="font-medium">Grund:</span> {reaction.rejection_reason}
              </p>
            )}
            {reaction.verdict === "ignored" && (
              <p className="mt-2 text-xs text-gray-500">
                Hat in diesem Zyklus entschieden, aber andere Impulse zitiert.
              </p>
            )}
            {reaction.verdict === "no_run" && (
              <p className="mt-2 text-xs text-gray-500">
                Keine Entscheidung in diesem Zyklus — der Impuls wurde nie bewertet.
              </p>
            )}
          </li>
        ))}
      </ul>
    </main>
  );
}
