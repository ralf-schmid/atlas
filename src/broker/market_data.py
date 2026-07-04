"""Market data access for fill-price simulation in InternalLedgerAdapter.

Both stock and crypto variants read from Alpaca's shared public market data —
identical data for every persona (Invariant #10, shared research pool).
"""

from __future__ import annotations

from typing import Protocol

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.models.trades import Trade
from alpaca.data.requests import CryptoLatestTradeRequest, StockLatestTradeRequest


class MarketDataProvider(Protocol):
    def get_last_price(self, symbol: str) -> float: ...


class AlpacaStockMarketDataProvider:
    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = StockHistoricalDataClient(api_key, secret_key)

    def get_last_price(self, symbol: str) -> float:
        trades = self._client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol)
        )
        trade = trades[symbol]
        assert isinstance(trade, Trade)
        return float(trade.price)


class AlpacaCryptoMarketDataProvider:
    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = CryptoHistoricalDataClient(api_key, secret_key)

    def get_last_price(self, symbol: str) -> float:
        trades = self._client.get_crypto_latest_trade(
            CryptoLatestTradeRequest(symbol_or_symbols=symbol)
        )
        trade = trades[symbol]
        assert isinstance(trade, Trade)
        return float(trade.price)
