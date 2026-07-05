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

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export async function getPersonaSnapshot(
  persona: string,
): Promise<PortfolioSnapshot | null> {
  const response = await fetch(`${API_URL}/api/personas/${persona}/snapshot`, {
    cache: "no-store",
  });

  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return (await response.json()) as PortfolioSnapshot;
}
