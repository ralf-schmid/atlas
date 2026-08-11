from unittest.mock import MagicMock, patch

import pytest
from alpaca.common.exceptions import APIError
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade

from src.broker.market_data import AlpacaCryptoMarketDataProvider, AlpacaStockMarketDataProvider


def _trade(symbol: str, price: float) -> Trade:
    return Trade.model_construct(symbol=symbol, price=price)


def test_stock_provider_returns_last_trade_price():
    with patch("src.broker.market_data.StockHistoricalDataClient") as mock_cls:
        client = mock_cls.return_value
        client.get_stock_latest_trade.return_value = {"AAPL": _trade("AAPL", 150.25)}

        provider = AlpacaStockMarketDataProvider(api_key="key", secret_key="secret")
        price = provider.get_last_price("AAPL")

        mock_cls.assert_called_once_with("key", "secret")
        assert price == 150.25


def test_crypto_provider_returns_last_trade_price():
    with patch("src.broker.market_data.CryptoHistoricalDataClient") as mock_cls:
        client = mock_cls.return_value
        client.get_crypto_latest_trade.return_value = {"BTC/USD": _trade("BTC/USD", 65000.0)}

        provider = AlpacaCryptoMarketDataProvider(api_key="key", secret_key="secret")
        price = provider.get_last_price("BTC/USD")

        mock_cls.assert_called_once_with("key", "secret")
        assert price == 65000.0


# --- F104: quoted spread ---


def _quote(symbol: str, bid: float | None, ask: float | None) -> Quote:
    return Quote.model_construct(symbol=symbol, bid_price=bid, ask_price=ask)


def test_stock_provider_computes_spread_bps_from_latest_quote():
    """Bid 99.90 / ask 100.10 -> spread 0.20 on a mid of 100.00 = 20 bps."""
    with patch("src.broker.market_data.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_latest_quote.return_value = {
            "AAPL": _quote("AAPL", 99.90, 100.10)
        }

        provider = AlpacaStockMarketDataProvider(api_key="key", secret_key="secret")

        assert provider.get_quote_spread_bps("AAPL") == pytest.approx(20.0)


def test_crypto_provider_computes_spread_bps_from_latest_quote():
    with patch("src.broker.market_data.CryptoHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_crypto_latest_quote.return_value = {
            "BTC/USD": _quote("BTC/USD", 64_900.0, 65_100.0)
        }

        provider = AlpacaCryptoMarketDataProvider(api_key="key", secret_key="secret")

        assert provider.get_quote_spread_bps("BTC/USD") == pytest.approx(30.769, rel=1e-3)


@pytest.mark.parametrize(
    "bid,ask",
    [
        (None, 100.10),  # no bid side
        (99.90, None),  # no ask side
        (0.0, 100.10),  # zero price — would divide by a meaningless mid
        (100.10, 99.90),  # crossed book
    ],
)
def test_spread_bps_returns_none_for_unusable_quote(bid, ask):
    """F104: an unusable quote yields None so the caller keeps the flat rate,
    instead of recording a nonsense spread against the order."""
    with patch("src.broker.market_data.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_latest_quote.return_value = {
            "AAPL": _quote("AAPL", bid, ask)
        }

        provider = AlpacaStockMarketDataProvider(api_key="key", secret_key="secret")

        assert provider.get_quote_spread_bps("AAPL") is None


# --- F092: validate_credentials ---


def test_stock_provider_validate_credentials_calls_api():
    with patch("src.broker.market_data.StockHistoricalDataClient") as mock_cls:
        provider = AlpacaStockMarketDataProvider(api_key="key", secret_key="secret")
        provider.validate_credentials()
        mock_cls.return_value.get_stock_latest_trade.assert_called_once()


def test_crypto_provider_validate_credentials_calls_api():
    with patch("src.broker.market_data.CryptoHistoricalDataClient") as mock_cls:
        provider = AlpacaCryptoMarketDataProvider(api_key="key", secret_key="secret")
        provider.validate_credentials()
        mock_cls.return_value.get_crypto_latest_trade.assert_called_once()


def test_stock_provider_validate_credentials_propagates_api_error():
    with patch("src.broker.market_data.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_latest_trade.side_effect = APIError(
            "401 Unauthorized", MagicMock()
        )
        provider = AlpacaStockMarketDataProvider(api_key="bad-key", secret_key="bad-secret")
        with pytest.raises(APIError, match="401"):
            provider.validate_credentials()


def test_crypto_provider_validate_credentials_propagates_api_error():
    with patch("src.broker.market_data.CryptoHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_crypto_latest_trade.side_effect = APIError(
            "401 Unauthorized", MagicMock()
        )
        provider = AlpacaCryptoMarketDataProvider(api_key="bad-key", secret_key="bad-secret")
        with pytest.raises(APIError, match="401"):
            provider.validate_credentials()
