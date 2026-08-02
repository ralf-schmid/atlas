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

export interface PortfolioHistoryPoint {
  ts: string;
  total_value: number;
  position_value: number;
  cash: number;
}

export interface PortfolioHistorySeries {
  persona: string;
  display_name: string;
  points: PortfolioHistoryPoint[];
}

export interface PortfolioHistory {
  start: string;
  start_capital: number;
  series: PortfolioHistorySeries[];
}

export interface LeaderboardRow {
  rank: number;
  persona: string;
  display_name: string;
  total_value: number;
  raw_return: number;
  adjusted_return: number;
  slippage_malus_usd: number | null;
  sortino: number | null;
  max_drawdown: number;
  trade_count: number;
  open_positions: number;
  sparkline: number[];
}

export interface LeaderboardBenchmark {
  symbol: string;
  total_value: number;
  raw_return: number;
  sparkline: number[];
}

export interface Leaderboard {
  start: string;
  start_capital: number;
  sort: "raw" | "adjusted";
  has_reviews: boolean;
  trading_days: number;
  rows: LeaderboardRow[];
  benchmark: LeaderboardBenchmark | null;
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

export interface DecisionExpectation {
  entry_price: number | null;
  stop_loss_price: number | null;
  target_price: number | null;
  horizon_days: number | null;
}

export interface DecisionOutcome {
  order_status: string;
  quantity: number | null;
  fill_price: number | null;
  filled_at: string | null;
}

export interface DecisionReview {
  verdict: string;
  reviewed_at: string;
  deviation: number | null;
  slippage_malus: number | null;
  lessons_text: string | null;
}

export type DecisionFilter = "all" | "traded" | "rejected" | "hold";

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
  expected: DecisionExpectation;
  outcome: DecisionOutcome | null;
  review: DecisionReview | null;
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

export async function getPortfolioHistory(): Promise<PortfolioHistory | null> {
  return getJson<PortfolioHistory>("/api/portfolios/history");
}

export async function getLeaderboard(
  sort: "raw" | "adjusted",
): Promise<Leaderboard | null> {
  return getJson<Leaderboard>(`/api/leaderboard?sort=${sort}`);
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
  filter: DecisionFilter = "all",
): Promise<Decision[]> {
  return (
    (await getJson<Decision[]>(
      `/api/personas/${persona}/decisions?filter=${filter}`,
    )) ?? []
  );
}

export async function getHoldingChart(
  persona: string,
  instrument: string,
): Promise<HoldingChart | null> {
  return getJson<HoldingChart>(
    `/api/personas/${persona}/chart?instrument=${encodeURIComponent(instrument)}`,
  );
}
