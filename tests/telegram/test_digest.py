import datetime

from src.telegram.digest import DigestData, PersonaDigest, render_daily_digest


def test_render_daily_digest_contains_all_required_fields():
    data = DigestData(
        trading_day=datetime.date(2026, 7, 5),
        personas=[
            PersonaDigest(
                name="VULTURE",
                trades_today=4,
                portfolio_value_usd=5200.0,
                cash_usd=1200.0,
                open_positions=8,
                llm_cost_usd=0.35,
            ),
            PersonaDigest(
                name="GUARDIAN",
                trades_today=0,
                portfolio_value_usd=4980.0,
                cash_usd=1500.0,
                open_positions=2,
                llm_cost_usd=0.10,
            ),
        ],
    )

    digest = render_daily_digest(data)

    assert "05.07.2026" in digest
    assert "VULTURE: 4 Trades" in digest
    assert "$5200.00" in digest.replace(",", "")
    assert "GUARDIAN: 0 Trades" in digest
    assert "Gesamt: $10180.00" in digest.replace(",", "")
    assert "LLM-Kosten gesamt: $0.4500" in digest


def test_digest_totals_are_computed_properties():
    data = DigestData(
        trading_day=datetime.date(2026, 7, 5),
        personas=[
            PersonaDigest(
                name="VULTURE",
                trades_today=1,
                portfolio_value_usd=100.0,
                cash_usd=10.0,
                open_positions=1,
                llm_cost_usd=0.01,
            ),
        ],
    )

    assert data.total_portfolio_value_usd == 100.0
    assert data.total_llm_cost_usd == 0.01
