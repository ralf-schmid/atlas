// German display labels for backend enum/string values — presentational only,
// the API keeps the English source_type/action/status strings.

const ACTION_LABELS: Record<string, string> = {
  buy: "Kaufen",
  sell: "Verkaufen",
  hold: "Halten",
  close: "Schließen",
  reject_idea: "Idee verworfen",
};

const DECISION_STATUS_LABELS: Record<string, string> = {
  pending: "Ausstehend",
  risk_rejected: "Risk-Gate abgelehnt",
  hitl_pending: "Wartet auf Freigabe",
  hitl_rejected: "Abgelehnt (Freigabe)",
  approved: "Freigegeben",
  executed: "Ausgeführt",
  recorded: "Erfasst",
};

const ORDER_STATUS_LABELS: Record<string, string> = {
  new: "Neu",
  filled: "Ausgeführt",
  partially_filled: "Teilweise ausgeführt",
  canceled: "Storniert",
  rejected: "Abgelehnt",
  expired: "Abgelaufen",
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  publication_article: "Zeitschrift",
  edgar_filing: "SEC-Filing (EDGAR)",
  aktienfinder_snapshot: "aktienfinder.de",
  screener_result: "Screener (Kursdaten)",
  musterdepot_transaction: "Aktionär-Musterdepot",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

export function decisionStatusLabel(status: string): string {
  return DECISION_STATUS_LABELS[status] ?? status;
}

export function orderStatusLabel(status: string): string {
  return ORDER_STATUS_LABELS[status] ?? status;
}

export function sourceTypeLabel(sourceType: string): string {
  return SOURCE_TYPE_LABELS[sourceType] ?? sourceType;
}

export function ageDaysLabel(ageDays: number | null): string {
  if (ageDays === null) {
    return "Alter unbekannt";
  }
  if (ageDays < 1) {
    return "heute";
  }
  if (ageDays < 2) {
    return "1 Tag alt";
  }
  return `${Math.round(ageDays)} Tage alt`;
}
