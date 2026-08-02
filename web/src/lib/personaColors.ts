// Fixed persona → line color mapping (F100). Fixed, not derived from the series
// order, so a persona keeps the same color across both charts and the legend.
const PERSONA_COLORS: Record<string, string> = {
  VULTURE: "#b45309",
  HYPE: "#c026d3",
  GUARDIAN: "#0f766e",
  CHARTIST: "#1d4ed8",
  CONTRA: "#b91c1c",
  CRYPTOR: "#4d7c0f",
};

export function personaColor(persona: string): string {
  return PERSONA_COLORS[persona] ?? "#4b5563";
}
