import type { Decision } from "@/lib/api";
import {
  actionLabel,
  ageDaysLabel,
  decisionStatusLabel,
  orderStatusLabel,
  reviewVerdictLabel,
  sourceTypeLabel,
} from "@/lib/labels";

const currency = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "USD",
});

const dateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
});

function price(value: number | null): string {
  return value === null ? "–" : currency.format(value);
}

/** One journal entry: what the persona decided, on which impulses, what it
 *  expected, what the broker did, and how the review judged it (F086). */
export default function DecisionCard({ decision }: { decision: Decision }) {
  const { expected, outcome, review } = decision;
  const hasExpectation =
    expected.entry_price !== null ||
    expected.stop_loss_price !== null ||
    expected.target_price !== null;

  return (
    <article className="rounded-xl border border-gray-200 p-4 text-sm shadow-sm">
      <div className="flex items-baseline justify-between gap-2">
        <p className="min-w-0 truncate font-semibold">
          {actionLabel(decision.action)} {decision.instrument}
        </p>
        <p className="shrink-0 text-xs text-gray-500">
          {decisionStatusLabel(decision.status)}
        </p>
      </div>
      <p className="text-xs text-gray-500">
        {dateTime.format(new Date(decision.ts))}
        {decision.conviction !== null &&
          ` · Sicherheit ${(decision.conviction * 100).toFixed(0)} %`}
      </p>

      <p className="mt-2 text-gray-700">{decision.thesis_text}</p>

      {decision.rejection_reason !== null && (
        <p className="mt-2 rounded-lg bg-gray-50 p-2 text-xs text-gray-600">
          <span className="font-medium">Verworfen:</span> {decision.rejection_reason}
        </p>
      )}

      {(hasExpectation || outcome !== null) && (
        <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 border-t border-gray-100 pt-2 text-xs">
          <dt className="text-gray-500">Erwartet</dt>
          <dd className="text-right text-gray-800">
            {price(expected.entry_price)}
            {expected.stop_loss_price !== null && ` · Stop ${price(expected.stop_loss_price)}`}
          </dd>

          {expected.target_price !== null && (
            <>
              <dt className="text-gray-500">Kursziel</dt>
              <dd className="text-right text-gray-800">
                {price(expected.target_price)}
                {expected.horizon_days !== null && ` · ${expected.horizon_days} Tage`}
              </dd>
            </>
          )}

          {outcome !== null && (
            <>
              <dt className="text-gray-500">Ist</dt>
              <dd className="text-right text-gray-800">
                {orderStatusLabel(outcome.order_status)}
                {outcome.fill_price !== null && ` @ ${price(outcome.fill_price)}`}
                {outcome.quantity !== null && ` · ${outcome.quantity} Stk.`}
              </dd>
            </>
          )}
        </dl>
      )}

      {review !== null && (
        <div className="mt-3 rounded-lg bg-gray-50 p-2 text-xs">
          <p className="font-medium text-gray-800">
            Review: {reviewVerdictLabel(review.verdict)}
            {review.deviation !== null &&
              ` · Abweichung ${(review.deviation * 100).toFixed(1)} %`}
          </p>
          {review.lessons_text !== null && (
            <p className="mt-1 text-gray-600">{review.lessons_text}</p>
          )}
        </div>
      )}

      {decision.research_items.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 border-t border-gray-100 pt-2">
          {decision.research_items.map((item) => (
            // line-clamp: a market_overview summary is a full markdown analysis and
            // would bury the decision it belongs to (live-hit 02.08.2026).
            <li key={item.id} className="line-clamp-2 text-xs text-gray-600">
              <span className="font-medium">{sourceTypeLabel(item.source_type)}</span> ·{" "}
              {ageDaysLabel(item.age_days)} —{" "}
              {item.url === null ? (
                item.summary
              ) : (
                <a href={item.url} className="underline" rel="noreferrer noopener">
                  {item.summary}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
