"""Daily digest — plain code over structured data, no LLM (ARCHITECTURE.md §7 Punkt 3)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from jinja2 import Environment

_TEMPLATE_SOURCE = """\
\U0001f4ca Tagesdigest {{ trading_day.strftime('%d.%m.%Y') }}

{% for p in personas -%}
{{ p.name }}: {{ p.trades_today }} Trades, Depotwert ${{ '%.2f'|format(p.portfolio_value_usd) }}, \
Cash ${{ '%.2f'|format(p.cash_usd) }}, {{ p.open_positions }} offene Positionen, \
LLM-Kosten ${{ '%.4f'|format(p.llm_cost_usd) }}
{% endfor %}
Gesamt: ${{ '%.2f'|format(total_portfolio_value_usd) }} | \
LLM-Kosten gesamt: ${{ '%.4f'|format(total_llm_cost_usd) }}\
"""

_env = Environment(autoescape=False)  # noqa: S701 — plain text digest, not HTML, no untrusted input
_template = _env.from_string(_TEMPLATE_SOURCE)


@dataclass(frozen=True, slots=True)
class PersonaDigest:
    name: str
    trades_today: int
    portfolio_value_usd: float
    cash_usd: float
    open_positions: int
    llm_cost_usd: float


@dataclass(frozen=True, slots=True)
class DigestData:
    trading_day: datetime.date
    personas: list[PersonaDigest]

    @property
    def total_portfolio_value_usd(self) -> float:
        return sum(p.portfolio_value_usd for p in self.personas)

    @property
    def total_llm_cost_usd(self) -> float:
        return sum(p.llm_cost_usd for p in self.personas)


def render_daily_digest(data: DigestData) -> str:
    return _template.render(
        trading_day=data.trading_day,
        personas=data.personas,
        total_portfolio_value_usd=data.total_portfolio_value_usd,
        total_llm_cost_usd=data.total_llm_cost_usd,
    )
