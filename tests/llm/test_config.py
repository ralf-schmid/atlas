from src.llm.config import load_llm_config


def test_load_llm_config_contains_all_agent_roles():
    config = load_llm_config()

    expected_roles = {"market_research", "news_research", "persona_analysis", "trading", "review"}
    assert expected_roles.issubset(config.roles.keys())


def test_load_llm_config_base_url_defaults_to_yaml_value():
    config = load_llm_config()

    assert config.base_url == "http://localhost:4000"


def test_load_llm_config_base_url_overridden_by_env(monkeypatch):
    """The scheduler container sets this — its own "localhost" isn't the litellm
    service's, unlike host-run scripts (scripts/run_cycle.py)."""
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000")

    config = load_llm_config()

    assert config.base_url == "http://litellm:4000"


def test_load_llm_config_caps_match_spec():
    config = load_llm_config()

    assert config.caps.system_daily_usd == 5.0
    assert config.caps.persona_daily_usd == 1.0
    assert config.caps.monthly_soft_cap_usd == 120.0
    assert config.caps.monthly_soft_cap_warn_pct == 0.8


def test_shared_roles_are_marked_shared():
    config = load_llm_config()

    assert config.roles["market_research"].shared is True
    assert config.roles["persona_analysis"].shared is False


def test_no_local_llm_providers_in_trading_path():
    config = load_llm_config()

    providers = {role.provider for role in config.roles.values()}
    assert "ollama" not in providers
    assert providers <= {"anthropic", "groq"}
