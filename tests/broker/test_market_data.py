from unittest.mock import patch

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
