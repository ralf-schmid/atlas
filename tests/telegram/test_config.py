import pytest

from src.telegram.config import load_config


def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    config = load_config()

    assert config.bot_token == "dummy-token"
    assert config.allowed_chat_id == 12345


def test_load_config_missing_token_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        load_config()


def test_load_config_missing_chat_id_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        load_config()


def test_load_config_non_integer_chat_id_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "not-a-number")

    with pytest.raises(ValueError, match="must be an integer"):
        load_config()
