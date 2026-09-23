from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Timeframe(str, Enum):
    """Canonical XAUUSD intraday timeframes for analysis and execution."""

    M1 = "1m"
    M5 = "5m"


class Candle(BaseModel):
    """Single OHLCV candle for a commodity instrument on a specific timeframe."""

    symbol: str = Field(description="Trading symbol, e.g. XAUUSD")
    timestamp: str = Field(description="UTC ISO-8601 timestamp")
    open: float
    high: float
    low: float
    close: float
    volume: float | int
    timeframe: Timeframe = Field(default=Timeframe.M5)


class MarketTick(BaseModel):
    """Tick-level market snapshot used for spread and liquidity analysis."""

    symbol: str = Field(description="Trading symbol, e.g. XAUUSD")
    timestamp: str = Field(description="UTC ISO-8601 timestamp")
    bid: float
    ask: float
    last: float
    volume: float | int = 0
    spread: float | None = None


__all__ = ["Candle", "MarketTick", "Timeframe"]
