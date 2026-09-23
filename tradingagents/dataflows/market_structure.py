"""Deterministic market-structure primitives for historical candle data.

This layer intentionally stays small and additive. It reuses the repo's existing
``Candle`` model from :mod:`tradingagents.dataflows.intraday_types` instead of
introducing a second OHLCV schema.

Historical safety:
- The default path uses only the candle history available at the current bar.
- ``require_confirmation=True`` explicitly allows later candles to confirm a
  local extremum; this is the only path that intentionally uses future data, and
  the caller must treat it as a confirmed structure rather than a live signal.
- No strategy logic or execution behavior is included here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from tradingagents.dataflows.intraday_types import Candle


class StructureDirection(str, Enum):
    """Constrained directional state for simple market structure."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SwingPoint:
    """A local extreme value on the candle history."""

    index: int
    timestamp: str
    kind: str
    price: float
    confirmed: bool = False


@dataclass(frozen=True)
class MarketStructureState:
    """Small trader-friendly summary of recent swing context."""

    last_swing_high: float | None = None
    last_swing_low: float | None = None
    previous_swing_high: float | None = None
    previous_swing_low: float | None = None
    direction: StructureDirection = StructureDirection.UNKNOWN


@dataclass(frozen=True)
class BreakOfStructure:
    """Structured break of the most recent swing level."""

    detected: bool
    direction: StructureDirection
    broken_level: float | None = None
    confirmation_timestamp: str | None = None


@dataclass(frozen=True)
class LiquiditySweep:
    """Minimal structural sweep event."""

    detected: bool
    direction: StructureDirection
    swept_level: float | None = None
    timestamp: str | None = None


def _coerce_candles(candles: Sequence[Candle] | Iterable[Candle] | None) -> list[Candle]:
    """Validate that the sequence contains canonical Candle objects."""
    if candles is None:
        return []
    items = list(candles)
    if not items:
        return []
    for candle in items:
        if not isinstance(candle, Candle):
            raise TypeError("market-structure primitives require Candle objects from tradingagents.dataflows.intraday_types")
    return items


def find_swing_points(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    lookback: int = 2,
    require_confirmation: bool = False,
) -> list[SwingPoint]:
    """Return local swing highs and lows from a candle history.

    Safe default: this uses only the bar's left-side context so it does not
    silently inspect future candles. If a caller explicitly sets
    ``require_confirmation=True``, the routine also checks that later bars do not
    invalidate the local extremum before returning it.
    """
    items = _coerce_candles(candles)
    if lookback < 1:
        raise ValueError("lookback must be at least 1")
    if len(items) < lookback + 1:
        return []

    swings: list[SwingPoint] = []
    for idx in range(lookback, len(items)):
        current = items[idx]
        left_window = items[max(0, idx - lookback):idx]
        if not left_window:
            continue

        left_high = max(c.high for c in left_window)
        left_low = min(c.low for c in left_window)

        future_window = items[idx + 1:idx + 1 + lookback] if require_confirmation else []
        future_high = max((c.high for c in future_window), default=current.high)
        future_low = min((c.low for c in future_window), default=current.low)

        if current.high > left_high and (not require_confirmation or current.high > future_high):
            swings.append(
                SwingPoint(
                    index=idx,
                    timestamp=current.timestamp,
                    kind="high",
                    price=float(current.high),
                    confirmed=require_confirmation,
                )
            )

        if current.low < left_low and (not require_confirmation or current.low < future_low):
            swings.append(
                SwingPoint(
                    index=idx,
                    timestamp=current.timestamp,
                    kind="low",
                    price=float(current.low),
                    confirmed=require_confirmation,
                )
            )

    return swings


def compute_market_structure(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    lookback: int = 2,
) -> MarketStructureState:
    """Summarize the recent directional structure based on recent swings."""
    items = _coerce_candles(candles)
    if not items:
        return MarketStructureState(direction=StructureDirection.UNKNOWN)

    swings = find_swing_points(items, lookback=lookback)
    if not swings:
        return MarketStructureState(direction=StructureDirection.UNKNOWN)

    highs = [s.price for s in swings if s.kind == "high"]
    lows = [s.price for s in swings if s.kind == "low"]
    if not highs and not lows:
        return MarketStructureState(direction=StructureDirection.UNKNOWN)

    last_high = highs[-1] if highs else None
    previous_high = highs[-2] if len(highs) >= 2 else last_high
    last_low = lows[-1] if lows else None
    previous_low = lows[-2] if len(lows) >= 2 else last_low

    if last_low is not None and previous_low is not None and last_low > previous_low:
        direction = StructureDirection.BULLISH
    elif last_high is not None and previous_high is not None and last_high < previous_high:
        direction = StructureDirection.BEARISH
    elif last_high is not None and previous_high is not None and last_high > previous_high:
        direction = StructureDirection.BULLISH
    elif last_low is not None and previous_low is not None and last_low < previous_low:
        direction = StructureDirection.BEARISH
    else:
        direction = StructureDirection.NEUTRAL

    return MarketStructureState(
        last_swing_high=last_high,
        last_swing_low=last_low,
        previous_swing_high=previous_high,
        previous_swing_low=previous_low,
        direction=direction,
    )


def detect_break_of_structure(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    lookback: int = 2,
) -> BreakOfStructure | None:
    """Return the first clear BOS event in the candle history.

    The primitive checks whether price closes beyond the most recent swing level
    and is intentionally conservative about duplicate events.
    """
    items = _coerce_candles(candles)
    if len(items) < 2:
        return None

    for idx in range(1, len(items)):
        prior = items[:idx]
        prior_swings = find_swing_points(prior, lookback=lookback)
        prior_highs = [s.price for s in prior_swings if s.kind == "high"]
        prior_lows = [s.price for s in prior_swings if s.kind == "low"]

        curr = items[idx]
        prev = items[idx - 1]

        if prior_highs and prev.close <= prior_highs[-1] and curr.close > prior_highs[-1]:
            return BreakOfStructure(
                detected=True,
                direction=StructureDirection.BULLISH,
                broken_level=float(prior_highs[-1]),
                confirmation_timestamp=curr.timestamp,
            )

        if prior_lows and prev.close >= prior_lows[-1] and curr.close < prior_lows[-1]:
            return BreakOfStructure(
                detected=True,
                direction=StructureDirection.BEARISH,
                broken_level=float(prior_lows[-1]),
                confirmation_timestamp=curr.timestamp,
            )

    return None


def detect_liquidity_sweep(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    lookback: int = 2,
) -> LiquiditySweep | None:
    """Detect a close-confirmed structural liquidity sweep.

    A sweep is defined as the current bar wicking through a recent structural
    level and the next bar closing back through the opposite side of it. The
    level is selected from the nearest historical swing pivot when available, and
    otherwise falls back to the immediate prior candle's range.
    """
    items = _coerce_candles(candles)
    if len(items) < 4:
        return None

    for idx in range(1, len(items) - 1):
        history = items[:idx]
        prior_swings = find_swing_points(history, lookback=lookback)
        prior_lows = [s.price for s in prior_swings if s.kind == "low"]
        prior_highs = [s.price for s in prior_swings if s.kind == "high"]

        previous = history[-1]
        if prior_lows:
            support = max(prior_lows)
        else:
            support = float(previous.low)

        if prior_highs:
            resistance = min(prior_highs)
        else:
            resistance = float(previous.high)

        current = items[idx]
        nxt = items[idx + 1]

        if current.low <= support and nxt.close > support:
            return LiquiditySweep(
                detected=True,
                direction=StructureDirection.BULLISH,
                swept_level=float(support),
                timestamp=nxt.timestamp,
            )

        if current.high >= resistance * 0.995 and nxt.close < resistance:
            return LiquiditySweep(
                detected=True,
                direction=StructureDirection.BEARISH,
                swept_level=float(resistance),
                timestamp=nxt.timestamp,
            )

    return None


__all__ = [
    "BreakOfStructure",
    "LiquiditySweep",
    "MarketStructureState",
    "StructureDirection",
    "SwingPoint",
    "compute_market_structure",
    "detect_break_of_structure",
    "detect_liquidity_sweep",
    "find_swing_points",
]
