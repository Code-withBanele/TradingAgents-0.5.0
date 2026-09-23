"""Deterministic technical indicator primitives for historical candle data.

These functions intentionally remain small and primitive: they answer a single
question for the supplied candle history and do not create trade signals,
entries, or risk logic.

The canonical market data type used here is the repo's existing
``Candle`` model from :mod:`tradingagents.dataflows.intraday_types`.
The volume field is treated as whatever the upstream feed provides (broker tick
volume, exchange volume, or synthetic volume from a data source). The indicator
layer never rewrites or infers a different semantics for volume.

Historical safety policy:
- calculations only use the supplied candle history
- no lookahead is introduced
- insufficient or flat data returns ``None`` or a zero value where that is the
  mathematically correct result for the primitive itself
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from tradingagents.dataflows.intraday_types import Candle


class StochasticState(str, Enum):
    """Simple normalized state for stochastic oscillator values."""

    OVERBOUGHT = "OVERBOUGHT"
    OVERSOLD = "OVERSOLD"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class StochasticResult:
    """A deterministic stochastic oscillator reading."""

    k: float
    d: float | None
    state: StochasticState
    timestamp: str


@dataclass(frozen=True)
class VWAPResult:
    """Volume-weighted average price for the analyzed candle history."""

    vwap: float
    timestamp: str
    session_start: str | None = None
    cumulative_volume: float = 0.0


@dataclass(frozen=True)
class VolatilityResult:
    """True range and ATR value for the current bar."""

    true_range: float
    atr: float | None
    timestamp: str


def _coerce_candles(candles: Sequence[Candle] | Iterable[Candle] | None) -> list[Candle]:
    if candles is None:
        return []
    items = list(candles)
    if not items:
        return []
    for candle in items:
        if not isinstance(candle, Candle):
            raise TypeError(
                "technical indicator primitives require Candle objects from tradingagents.dataflows.intraday_types"
            )
    return items


def _ensure_chronological(items: Sequence[Candle]) -> Sequence[Candle]:
    """Reject non-chronological inputs instead of silently reordering them."""
    for previous, current in zip(items, items[1:]):
        if previous.timestamp >= current.timestamp:
            raise ValueError("candles must be provided in chronological order")
    return items


def _typical_price(candle: Candle) -> float:
    return (float(candle.high) + float(candle.low) + float(candle.close)) / 3.0


def calculate_stochastic(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    k_period: int = 14,
    d_period: int = 3,
) -> StochasticResult | None:
    """Compute a deterministic stochastic oscillator using the last ``k_period`` candles.

    Convention used here:
    - ``%K`` = 100 * (close - lowest_low) / (highest_high - lowest_low)
    - ``%D`` = simple moving average of the trailing ``d_period`` ``%K`` values
      when enough history exists
    - if the high/low range is zero, ``%K`` resolves to ``0.0`` to avoid a
      divide-by-zero and to represent a flat stochastic range deterministically
    
    The primitive only reports the current state; it does not translate the
    result into a trade decision.
    """
    items = _coerce_candles(candles)
    if not items:
        return None
    items = _ensure_chronological(items)
    if k_period < 1:
        raise ValueError("k_period must be at least 1")
    if d_period < 1:
        raise ValueError("d_period must be at least 1")
    if len(items) < k_period:
        return None

    k_values: list[float] = []
    for idx in range(k_period - 1, len(items)):
        window = items[idx - k_period + 1 : idx + 1]
        highest_high = max(c.high for c in window)
        lowest_low = min(c.low for c in window)
        current_close = items[idx].close
        if highest_high == lowest_low:
            k = 0.0
        else:
            k = 100.0 * ((current_close - lowest_low) / (highest_high - lowest_low))
        k_values.append(float(k))

    if not k_values:
        return None

    k_value = float(k_values[-1])
    if len(k_values) < d_period:
        d_value = None
    else:
        d_window = k_values[-d_period:]
        d_value = sum(d_window) / len(d_window)

    if k_value >= 80.0 or (d_value is not None and d_value >= 80.0):
        state = StochasticState.OVERBOUGHT
    elif k_value <= 20.0 or (d_value is not None and d_value <= 20.0):
        state = StochasticState.OVERSOLD
    else:
        state = StochasticState.NEUTRAL
    return StochasticResult(k=k_value, d=None if d_value is None else float(d_value), state=state, timestamp=items[-1].timestamp)


def calculate_vwap(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    reset_session: bool = False,
    session_key: str | None = None,
) -> VWAPResult | None:
    """Compute the cumulative VWAP for the supplied candle history.

    Volume is the feed's native volume field; the indicator layer does not alter
    its semantics. If the source is broker tick volume or exchange volume, that
    value is used directly without reinterpretation.

    ``reset_session=True`` forces a session reset at a new day boundary by
    default, which keeps the primitive explicit for intraday XAUUSD analysis. A
    custom ``session_key`` can be supplied when a caller wants a different
    session boundary (for example, a manual exchange session identifier).
    """
    items = _coerce_candles(candles)
    if not items:
        return None
    items = _ensure_chronological(items)

    cumulative_volume = 0.0
    cumulative_price_volume = 0.0
    session_start: str | None = None

    for candle in items:
        if reset_session or session_key is not None:
            if session_key is not None:
                current_session = session_key
            else:
                current_session = candle.timestamp.split("T", 1)[0]
            if session_start is None or current_session != session_start:
                session_start = current_session
                cumulative_volume = 0.0
                cumulative_price_volume = 0.0

        volume = float(candle.volume)
        if volume <= 0:
            continue
        cumulative_volume += volume
        cumulative_price_volume += _typical_price(candle) * volume

    if cumulative_volume <= 0:
        return None

    return VWAPResult(
        vwap=float(cumulative_price_volume / cumulative_volume),
        timestamp=items[-1].timestamp,
        session_start=session_start,
        cumulative_volume=float(cumulative_volume),
    )


def calculate_true_range(candle: Candle, previous_close: float | None) -> float:
    """Return the true range for a single candle.

    Standard relationship used here:
    ``TR = max(high - low, abs(high - prev_close), abs(low - prev_close))``
    with a first-candle fallback of ``high - low`` when no previous close is
    available.
    """
    if not isinstance(candle, Candle):
        raise TypeError("calculate_true_range requires a Candle instance")
    high = float(candle.high)
    low = float(candle.low)
    if previous_close is None:
        return max(high - low, 0.0)
    prev_close = float(previous_close)
    return max(high - low, abs(high - prev_close), abs(low - prev_close), 0.0)


def calculate_atr(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    period: int = 14,
) -> VolatilityResult | None:
    """Compute the ATR for the latest candle in the supplied history.

    This uses the standard simple-moving-average true range over the trailing
    ``period`` bars, and returns ``None`` when the supplied data is insufficient
    to support a valid ATR value.
    """
    items = _coerce_candles(candles)
    if not items:
        return None
    items = _ensure_chronological(items)
    if period < 1:
        raise ValueError("period must be at least 1")
    if len(items) < 2:
        return None

    true_ranges: list[float] = []
    for idx in range(1, len(items)):
        true_ranges.append(calculate_true_range(items[idx], items[idx - 1].close))

    if len(true_ranges) < period:
        return None

    atr_value = sum(true_ranges[-period:]) / period
    current = items[-1]
    return VolatilityResult(
        true_range=float(true_ranges[-1]),
        atr=float(atr_value),
        timestamp=current.timestamp,
    )


__all__ = [
    "StochasticResult",
    "StochasticState",
    "VWAPResult",
    "VolatilityResult",
    "calculate_atr",
    "calculate_stochastic",
    "calculate_true_range",
    "calculate_vwap",
]
