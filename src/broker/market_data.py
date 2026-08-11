"""Market data access for fill-price simulation in InternalLedgerAdapter.

Both stock and crypto variants read from Alpaca's shared public market data —
identical data for every persona (Invariant #10, shared research pool).
"""

from __future__ import annotations

from typing import Protocol

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from alpaca.data.requests import (
    CryptoLatestQuoteRequest,
    CryptoLatestTradeRequest,
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
)


class MarketDataProvider(Protocol):
    def get_last_price(self, symbol: str) -> float: ...

    def validate_credentials(self) -> None: ...


class SpreadProvider(Protocol):
    """F104: the quoted bid/ask spread, read once per order to feed the slippage
    malus (`src/review/slippage.py`). Deliberately separate from
    `MarketDataProvider` — the internal ledger needs a fill price, not a spread."""

    def get_quote_spread_bps(self, symbol: str) -> float | None: ...


def _spread_bps(bid: float | None, ask: float | None) -> float | None:
    """Spread relative to the mid, in basis points. `None` for a quote we can't use
    (missing side, zero price, crossed book) — the caller then keeps the flat rate
    rather than recording a nonsense number."""
    if not bid or not ask or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2
    return (ask - bid) / mid * 10_000


class AlpacaStockMarketDataProvider:
    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = StockHistoricalDataClient(api_key, secret_key)

    def validate_credentials(self) -> None:
        self._client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols="SPY"))

    def get_last_price(self, symbol: str) -> float:
        trades = self._client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol)
        )
        trade = trades[symbol]
        assert isinstance(trade, Trade)
        return float(trade.price)

    def get_quote_spread_bps(self, symbol: str) -> float | None:
        quotes = self._client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol)
        )
        quote = quotes[symbol]
        assert isinstance(quote, Quote)
        return _spread_bps(quote.bid_price, quote.ask_price)


class AlpacaCryptoMarketDataProvider:
    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = CryptoHistoricalDataClient(api_key, secret_key)

    def validate_credentials(self) -> None:
        self._client.get_crypto_latest_trade(CryptoLatestTradeRequest(symbol_or_symbols="BTC/USD"))

    def get_last_price(self, symbol: str) -> float:
        trades = self._client.get_crypto_latest_trade(
            CryptoLatestTradeRequest(symbol_or_symbols=symbol)
        )
        trade = trades[symbol]
        assert isinstance(trade, Trade)
        return float(trade.price)

    def get_quote_spread_bps(self, symbol: str) -> float | None:
        quotes = self._client.get_crypto_latest_quote(
            CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
        )
        quote = quotes[symbol]
        assert isinstance(quote, Quote)
        return _spread_bps(quote.bid_price, quote.ask_price)
