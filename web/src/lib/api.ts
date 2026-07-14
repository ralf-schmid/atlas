export interface Position {
  instrument: string;
  qty: number;
  avg_price: number;
  market_value: number;
  pnl_unrealized: number;
}

export interface PortfolioSnapshot {
  persona: string;
  mode: "paper" | "live";
  ts: string;
  total_value: number;
  cash: number;
  pnl_realized: number;
  pnl_unrealized: number;
  positions: Position[];
}

export interface PersonaProfile {
  name: string;
  display_name: string;
  philosophy: string;
  universe: string;
  signals: string;
  holding_period: string;
  failure_mode: string;
}

export interface Holding {
  instrument: string;
  qty: number;
  avg_price: number;
  current_price: number;
  market_value: number;
  pnl_unrealized: number;
  pnl_unrealized_pct: number;
  last_buy_at: string | null;
}

export interface Transaction {
  decision_id: string;
  instrument: string;
  action: string;
  quantity: number | null;
  submitted_at: string;
  filled_at: string | null;
  fill_price: number | null;
  status: string;
  thesis_text: string;
}

export interface ChartBar {
  ts: string;
  close: number;
}

export interface ChartFillMarker {
  ts: string;
  price: number;
  qty: number;
  action: "buy" | "sell";
}

export interface ChartLivePrice {
  ts: string;
  price: number;
}

export interface HoldingChart {
  instrument: string;
  start: string;
  bars: ChartBar[];
  fills: ChartFillMarker[];
  live_price: ChartLivePrice | null;
}

export interface ResearchRef {
  id: string;
  source_type: string;
  summary: string;
  published_at: string | null;
  age_days: number | null;
  url: string | null;
}

export interface Decision {
  id: string;
  ts: string;
  instrument: string;
  action: string;
  status: string;
  conviction: number | null;
  thesis_text: string;
  rejection_reason: string | null;
  research_items: ResearchRef[];
}

const API_URL = process.env.API_URL ?? "http://localhost:8000";

async function getJson<T>(path: string): Promise<T | null> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });

  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function getPersonaSnapshot(
  persona: string,
): Promise<PortfolioSnapshot | null> {
  return getJson<PortfolioSnapshot>(`/api/personas/${persona}/snapshot`);
}

export async function getPersonaProfile(
  persona: string,
): Promise<PersonaProfile | null> {
  return getJson<PersonaProfile>(`/api/personas/${persona}/profile`);
}

export async function getPersonaHoldings(persona: string): Promise<Holding[]> {
  return (await getJson<Holding[]>(`/api/personas/${persona}/holdings`)) ?? [];
}

export async function getPersonaTransactions(
  persona: string,
): Promise<Transaction[]> {
  return (
    (await getJson<Transaction[]>(`/api/personas/${persona}/transactions`)) ?? []
  );
}

export async function getPersonaDecisions(
  persona: string,
): Promise<Decision[]> {
  return (await getJson<Decision[]>(`/api/personas/${persona}/decisions`)) ?? [];
}

export async function getHoldingChart(
  persona: string,
  instrument: string,
): Promise<HoldingChart | null> {
  return getJson<HoldingChart>(
    `/api/personas/${persona}/chart?instrument=${encodeURIComponent(instrument)}`,
  );
}
