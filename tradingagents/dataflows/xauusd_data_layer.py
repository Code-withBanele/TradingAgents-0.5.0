from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from tradingagents.dataflows.intraday_types import Candle, MarketTick, Timeframe
from tradingagents.dataflows.market_data_provider import (
    MarketDataProvider,
    create_market_data_provider,
)
from tradingagents.dataflows.state_reconciliation import canonicalize_timeframe
from tradingagents.dataflows.stockstats_utils import load_ohlcv
from tradingagents.xauusd_config import XAUUSD_CONFIG


class XAUUSDDataLayer:
    """Compatibility wrapper around the Phase 2 provider abstraction.

    This keeps older synchronous callers working while ensuring all XAUUSD market
    data flows through the same provider interface rather than creating a second,
    independent fetch implementation.
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        default_timeframe: str | Timeframe = Timeframe.M5,
        provider: MarketDataProvider | None = None,
    ):
        self.symbol = symbol.upper()
        self.default_timeframe = canonicalize_timeframe(default_timeframe)
        self.provider: MarketDataProvider = provider or create_market_data_provider(
            str(XAUUSD_CONFIG.get("provider", "mock")), symbol=self.symbol
        )

    async def get_historical_candles(
        self,
        start: datetime,
        end: datetime,
        *,
        timeframe: str | Timeframe | None = None,
    ) -> list[Candle]:
        """Fetch canonical candles through the configured provider abstraction.

        The older ``load_candles(curr_date)`` API remains for legacy callers;
        new provider-backed work should use this explicit historical range.
        """
        chosen = canonicalize_timeframe(timeframe or self.default_timeframe)
        return await self.provider.get_historical_candles(self.symbol, chosen, start, end)

    def load_candles(
        self,
        curr_date: str,
        *,
        timeframe: str | Timeframe | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Compatibility wrapper for existing XAUUSD callers.

        When the legacy OHLCV loader is used in the repo, preserve that behavior so
        older tests and code keep working. The provider abstraction remains the
        canonical new interface, but the compatibility layer intentionally does not
        silently replace the repo's established data-loading contract.
        """
        frame = load_ohlcv(self.symbol, curr_date, fill_gaps=True)
        chosen = canonicalize_timeframe(timeframe or self.default_timeframe)
        rows = frame.copy()
        if rows.empty:
            return []

        rows["Date"] = pd.to_datetime(rows["Date"], errors="coerce")
        rows = rows.dropna(subset=["Date"]).sort_values("Date")
        if limit is not None:
            rows = rows.tail(limit)

        candles: list[Candle] = []
        for _, row in rows.iterrows():
            volume = row.get("Volume", 0) or 0
            candles.append(
                Candle(
                    symbol=self.symbol,
                    timestamp=pd.Timestamp(row["Date"]).isoformat(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(volume),
                    timeframe=chosen,
                )
            )
        return candles

    def latest_market_tick(self, curr_date: str, *, bid: float | None = None, ask: float | None = None, last: float | None = None) -> MarketTick:
        """Return a canonical latest tick snapshot for the current run."""
        timestamp = pd.Timestamp(curr_date).isoformat()
        bid_value = float(bid if bid is not None else 0.0)
        ask_value = float(ask if ask is not None else 0.0)
        last_value = float(last if last is not None else (bid_value + ask_value) / 2.0 if bid_value or ask_value else 0.0)
        spread = None if bid_value == 0 or ask_value == 0 else ask_value - bid_value
        return MarketTick(
            symbol=self.symbol,
            timestamp=timestamp,
            bid=bid_value,
            ask=ask_value,
            last=last_value,
            volume=0,
            spread=spread,
        )

    def snapshot_state(self, curr_date: str, *, timeframe: str | Timeframe | None = None, limit: int | None = None) -> dict[str, Any]:
        """Return a canonical state dict suitable for reconciliation and graph state."""
        candles = self.load_candles(curr_date, timeframe=timeframe, limit=limit)
        latest = candles[-1] if candles else None
        canonical_timeframe = canonicalize_timeframe(timeframe or self.default_timeframe)
        return {
            "symbol": self.symbol,
            "timeframe": canonical_timeframe.value,
            "latest_timestamp": latest.timestamp if latest else None,
            "latest_close": float(latest.close) if latest else None,
            "candles": candles,
        }


__all__ = ["XAUUSDDataLayer"]
