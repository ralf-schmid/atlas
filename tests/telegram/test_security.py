from src.telegram.config import TelegramConfig
from src.telegram.security import is_authorized_chat


def test_is_authorized_chat_accepts_configured_id():
    config = TelegramConfig(bot_token="dummy", allowed_chat_id=12345)

    assert is_authorized_chat(12345, config) is True


def test_is_authorized_chat_rejects_other_id():
    config = TelegramConfig(bot_token="dummy", allowed_chat_id=12345)

    assert is_authorized_chat(99999, config) is False
