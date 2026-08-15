"""Spec loading and validation — F111 §8, tests 18-20."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.backtest.run import load_settings
from src.backtest.spec import (
    DEFAULT_STRATEGY_DIR,
    Condition,
    SpecError,
    load_all_strategies,
    load_strategy,
    symbol_asset_class,
)
from tests.backtest.conftest import write_spec


def test_all_shipped_strategies_load() -> None:
    """Test 18. A broken spec must fail here, in CI, not on the box at 2 a.m."""
    specs = load_all_strategies(DEFAULT_STRATEGY_DIR)
    names = {spec.name for spec in specs}

    assert names == {
        "chartist-proxy",
        "contra-proxy",
        "cryptor-proxy",
        "vulture-proxy",
        "baseline-sma-crossover",
    }
    for spec in specs:
        assert spec.entry, spec.name
        assert spec.guardrails.stop_loss_policy is not None, spec.name


def test_persona_specs_inherit_the_real_guardrails() -> None:
    """A proxy that restated the persona's limits could drift from them. It reads
    config/personas/*.yaml instead."""
    specs = {spec.name: spec for spec in load_all_strategies(DEFAULT_STRATEGY_DIR)}

    chartist = specs["chartist-proxy"]
    assert chartist.guardrails.name == "CHARTIST"
    assert chartist.guardrails.max_position_pct == 0.10
    assert chartist.guardrails.stop_loss_policy.type.value == "atr"

    cryptor = specs["cryptor-proxy"]
    assert cryptor.guardrails.max_position_pct == 0.20
    # Der Proxy bildet CRYPTORs Charter nach, er waehlt sich kein eigenes
    # Universum — deshalb gegen die Charter-Datei geprueft und nicht gegen eine
    # zweite Liste im Test. Sonst haette ADR-0016 (3 -> 10 Paare) zwei Stellen
    # auseinanderlaufen lassen, ohne dass es auffaellt.
    charter = yaml.safe_load((Path("config/personas/cryptor.yaml")).read_text(encoding="utf-8"))
    assert cryptor.universe.symbols == charter["universe_screen"]["universe"]


def test_unknown_signal_fails_at_load(tmp_path) -> None:
    """Test 19a."""
    with pytest.raises(SpecError, match="unknown signal"):
        write_spec(
            tmp_path,
            {
                "name": "broken",
                "description": "test",
                "guardrails": _guardrails(),
                "entry": [{"signal": "moon_phase", "op": "gt", "value": 1}],
            },
        )


def test_unknown_operator_fails_at_load(tmp_path) -> None:
    """Test 19b."""
    with pytest.raises(SpecError, match="operator"):
        write_spec(
            tmp_path,
            {
                "name": "broken",
                "description": "test",
                "guardrails": _guardrails(),
                "entry": [{"signal": "close", "op": "approximately", "value": 1}],
            },
        )


def test_categorical_signal_rejects_a_numeric_threshold(tmp_path) -> None:
    with pytest.raises(SpecError, match="string value"):
        write_spec(
            tmp_path,
            {
                "name": "broken",
                "description": "test",
                "guardrails": _guardrails(),
                "entry": [{"signal": "sma_crossover", "op": "eq", "value": 3}],
            },
        )


def test_screen_drift_is_caught(tmp_path) -> None:
    """The anti-drift guard from F111 §6.2: adding a screen criterion to a charter
    must break the proxy loudly instead of leaving it quietly out of date."""
    with pytest.raises(SpecError, match="market_cap_max"):
        write_spec(
            tmp_path,
            {
                "name": "drifting",
                "description": "test",
                "persona": "VULTURE",
                "screen_modelled": ["price_max", "daily_volume_min"],
                "entry": [{"signal": "close", "op": "lt", "value": 5}],
            },
        )


def test_persona_and_inline_guardrails_are_mutually_exclusive(tmp_path) -> None:
    with pytest.raises(SpecError, match="not both"):
        write_spec(
            tmp_path,
            {
                "name": "confused",
                "description": "test",
                "persona": "CRYPTOR",
                "screen_modelled": ["universe"],
                "guardrails": _guardrails(),
                "entry": [{"signal": "close", "op": "gt", "value": 1}],
            },
        )


def test_entry_is_required(tmp_path) -> None:
    with pytest.raises(SpecError, match="at least one condition"):
        write_spec(
            tmp_path,
            {"name": "empty", "description": "test", "guardrails": _guardrails(), "entry": []},
        )


def test_hype_and_guardian_have_no_spec_and_a_stated_reason() -> None:
    """Test 20. Both are absent by decision, and the reason is config, not folklore."""
    names = {spec.name for spec in load_all_strategies(DEFAULT_STRATEGY_DIR)}
    assert not any(name.startswith(("hype", "guardian")) for name in names)

    not_backtestable = load_settings().not_backtestable
    assert set(not_backtestable) == {"HYPE", "GUARDIAN"}
    assert "Zeitschriften" in not_backtestable["HYPE"]
    assert "aktienfinder" in not_backtestable["GUARDIAN"]


def test_only_referenced_signals_are_computed(tmp_path) -> None:
    spec = write_spec(
        tmp_path,
        {
            "name": "narrow",
            "description": "test",
            "guardrails": _guardrails(),
            "universe": {"filters": [{"signal": "volume", "op": "gte", "value": 1}]},
            "entry": [{"signal": "rsi14", "op": "lt", "value": 30}],
            "exit": [{"signal": "close", "op": "gt", "value": 1}],
        },
    )
    assert spec.referenced_signals() == {"volume", "rsi14", "close"}


def test_condition_treats_missing_values_as_no_signal() -> None:
    """The rule the whole engine leans on: an unavailable indicator neither opens nor
    closes a position."""
    assert Condition("rsi14", "lt", 30).matches(None) is False
    assert Condition("rsi14", "gt", 30).matches(None) is False
    assert Condition("sma_crossover", "eq", "golden_cross").matches(None) is False
    assert Condition("sma_crossover", "eq", "golden_cross").matches("golden_cross") is True


def test_shipped_strategy_files_are_valid_yaml_mappings() -> None:
    for path in sorted(DEFAULT_STRATEGY_DIR.glob("*.yaml")):
        assert isinstance(yaml.safe_load(path.read_text()), dict), path.name
        load_strategy(path)


def _guardrails() -> dict[str, object]:
    return {
        "name": "TEST",
        "max_position_pct": 0.1,
        "max_trades_per_day": 5,
        "max_open_positions": 10,
        "min_cash_pct": 0.0,
        "stop_loss_policy": {"type": "fixed", "max_loss_pct": 0.15},
    }


def test_every_shipped_spec_declares_its_asset_class() -> None:
    """F114 §5. A spec without `symbols` sees the whole universe, and since ADR-0016
    widened CRYPTOR's charter that universe contains ten crypto pairs. contra-proxy
    bought five of them (22 trades) although CONTRA trades US Mid/Large Caps.

    Declaring the class is therefore mandatory, not optional — an undeclared spec
    would silently inherit the mixed universe again the next time one is added.
    """
    for spec in load_all_strategies(DEFAULT_STRATEGY_DIR):
        assert spec.universe.asset_class is not None, spec.name
    by_name = {spec.name: spec for spec in load_all_strategies(DEFAULT_STRATEGY_DIR)}
    assert by_name["cryptor-proxy"].universe.asset_class == "crypto"
    for name in ("chartist-proxy", "contra-proxy", "vulture-proxy", "baseline-sma-crossover"):
        assert by_name[name].universe.asset_class == "equities", name


def test_unknown_asset_class_fails_at_load(tmp_path) -> None:
    with pytest.raises(SpecError, match="asset_class"):
        write_spec(
            tmp_path,
            {
                "name": "broken",
                "description": "test",
                "guardrails": _guardrails(),
                "universe": {"asset_class": "commodities"},
                "entry": [{"signal": "close", "op": "gt", "value": 1}],
            },
        )


def test_symbol_asset_class_uses_the_pair_notation() -> None:
    """Keyed on `BASE/QUOTE`, not on the spread config's substring list — otherwise
    adding a ticker there for pricing reasons would move symbols between universes."""
    assert symbol_asset_class("BTC/USD") == "crypto"
    assert symbol_asset_class("AAVE/USD") == "crypto"
    assert symbol_asset_class("AAPL") == "equities"
    assert symbol_asset_class("LINK") == "equities"  # the equity ticker, not the coin


class TestSpecValidationRefusals:
    """Every way a strategy file can be wrong, refused at load time.

    These branches are the anti-drift guard of the whole feature (F111 §6.2): a
    malformed spec that loads anyway would run *something* and label the artefact
    with the strategy it was supposed to be.
    """

    def test_top_level_must_be_a_mapping(self, tmp_path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- not\n- a mapping\n")
        with pytest.raises(SpecError, match="mapping"):
            load_strategy(path)

    def test_name_is_required(self, tmp_path) -> None:
        with pytest.raises(SpecError, match="name"):
            write_spec(tmp_path, {"description": "d", "guardrails": _guardrails(), "entry": []})

    def test_persona_must_be_a_string(self, tmp_path) -> None:
        with pytest.raises(SpecError, match="persona must be a string"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "persona": 42,
                    "entry": [{"signal": "close", "op": "gt", "value": 1}],
                },
            )

    @pytest.mark.parametrize("bad", [0, -3, "sieben"])
    def test_max_hold_days_must_be_a_positive_integer(self, tmp_path, bad) -> None:
        with pytest.raises(SpecError, match="max_hold_days"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "guardrails": _guardrails(),
                    "entry": [{"signal": "close", "op": "gt", "value": 1}],
                    "max_hold_days": bad,
                },
            )

    def test_a_spec_needs_guardrails_from_somewhere(self, tmp_path) -> None:
        with pytest.raises(SpecError, match="persona reference or a guardrails block"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "entry": [{"signal": "close", "op": "gt", "value": 1}],
                },
            )

    def test_incomplete_guardrails_block_is_rejected(self, tmp_path) -> None:
        """A missing stop-loss policy must not fall back to "no stop" — Invariante #4
        has no default."""
        with pytest.raises(SpecError, match="invalid guardrails block"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "guardrails": {"name": "X", "max_position_pct": 0.1},
                    "entry": [{"signal": "close", "op": "gt", "value": 1}],
                },
            )

    def test_universe_symbols_must_be_strings(self, tmp_path) -> None:
        with pytest.raises(SpecError, match="universe.symbols"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "guardrails": _guardrails(),
                    "universe": {"symbols": ["AAPL", 7]},
                    "entry": [{"signal": "close", "op": "gt", "value": 1}],
                },
            )

    def test_conditions_must_be_a_list_of_mappings(self, tmp_path) -> None:
        with pytest.raises(SpecError, match="entry must be a list"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "guardrails": _guardrails(),
                    "entry": {"signal": "close"},
                },
            )
        with pytest.raises(SpecError, match="entries must be mappings"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "guardrails": _guardrails(),
                    "entry": ["close > 1"],
                },
            )

    @pytest.mark.parametrize("bad", ["dreissig", True, None])
    def test_numeric_signal_rejects_a_non_numeric_threshold(self, tmp_path, bad) -> None:
        """`True` is caught deliberately: in Python it would compare as 1 and quietly
        become a threshold nobody wrote."""
        with pytest.raises(SpecError, match="needs a numeric value"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "guardrails": _guardrails(),
                    "entry": [{"signal": "rsi14", "op": "lt", "value": bad}],
                },
            )

    def test_declaring_a_screen_key_the_persona_does_not_have(self, tmp_path) -> None:
        with pytest.raises(SpecError, match="does not have"):
            write_spec(
                tmp_path,
                {
                    "name": "n",
                    "description": "d",
                    "persona": "CONTRA",
                    "screen_modelled": ["drawdown_min_pct", "drawdown_window_days", "erfunden"],
                    "entry": [{"signal": "close", "op": "gt", "value": 1}],
                },
            )


def test_categorical_condition_supports_negation() -> None:
    """`ne` on a categorical signal: "any day that is not a death cross"."""
    condition = Condition("sma_crossover", "ne", "death_cross")

    assert condition.matches("golden_cross") is True
    assert condition.matches("death_cross") is False
    assert condition.matches(None) is False


def test_categorical_signal_rejects_ordering_operators() -> None:
    """A crossover has no order, so `lt` on it is meaningless rather than false."""
    assert Condition("sma_crossover", "lt", "golden_cross").matches("death_cross") is False
