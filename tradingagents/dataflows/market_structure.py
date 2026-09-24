"""Deterministic market-structure primitives for historical candle data.

This layer intentionally stays small and additive. It reuses the repo's existing
``Candle`` model from :mod:`tradingagents.dataflows.intraday_types` instead of
introducing a second OHLCV schema.

Historical safety:
- The default path uses only the candle history available at the current bar.
- ``require_confirmation=True`` explicitly allows later candles to confirm a
  local extremum; this is the only path that intentionally uses future data, and
  the caller must treat it as a confirmed structure rather than a live signal.
- Strategy evaluation is deterministic and candidate-only; execution behavior is
  not included here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Sequence

import pytz

from tradingagents.dataflows.intraday_types import Candle
from tradingagents.dataflows.technical_indicators import calculate_atr


class StructureDirection(str, Enum):
    """Constrained directional state for simple market structure."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class SessionName(str, Enum):
    """Canonical intraday sessions for XAUUSD analysis."""

    ASIA = "ASIA"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    LONDON_NEW_YORK_OVERLAP = "LONDON_NEW_YORK_OVERLAP"
    OUTSIDE_CONFIGURED_SESSION = "OUTSIDE_CONFIGURED_SESSION"


class PriceLocation(str, Enum):
    """Premium/discount context for a value relative to the dealing range."""

    PREMIUM = "PREMIUM"
    DISCOUNT = "DISCOUNT"
    EQUILIBRIUM = "EQUILIBRIUM"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SwingPoint:
    """A local extreme value on the candle history."""

    index: int
    timestamp: str
    kind: str
    price: float
    confirmed: bool = False
    confirmation_index: int | None = None


@dataclass(frozen=True)
class MarketStructureState:
    """Small trader-friendly summary of recent swing context."""

    last_swing_high: float | None = None
    last_swing_low: float | None = None
    previous_swing_high: float | None = None
    previous_swing_low: float | None = None
    direction: StructureDirection = StructureDirection.UNKNOWN
    session: SessionName | None = None
    session_open: str | None = None
    session_high: float | None = None
    session_low: float | None = None
    previous_session_high: float | None = None
    previous_session_low: float | None = None


@dataclass(frozen=True)
class BreakOfStructure:
    """Structured break of the most recent swing level."""

    detected: bool
    direction: StructureDirection
    broken_level: float | None = None
    confirmation_timestamp: str | None = None
    confirmation_index: int | None = None


@dataclass(frozen=True)
class LiquiditySweep:
    """Minimal structural sweep event."""

    detected: bool
    direction: StructureDirection
    swept_level: float | None = None
    timestamp: str | None = None
    sweep_index: int | None = None
    confirmation_index: int | None = None


@dataclass(frozen=True)
class FairValueGap:
    """Deterministic three-candle imbalance gap with explicit lifecycle state."""

    direction: StructureDirection
    low: float
    high: float
    created_at: str
    timestamp: str
    timeframe: str = "5m"
    size: float = 0.0
    status: str = "FVG_ACTIVE"
    mitigation_status: str = "UNMITIGATED"
    invalidation_status: str = "VALID"
    formation_index: int | None = None
    confirmation_index: int | None = None


@dataclass(frozen=True)
class InverseFairValueGap:
    """Transition from one imbalance to an opposite imbalance."""

    original_direction: StructureDirection
    new_direction: StructureDirection
    original_low: float | None = None
    original_high: float | None = None
    new_low: float | None = None
    new_high: float | None = None
    transition_timestamp: str | None = None
    status: str = "ACTIVE"


@dataclass(frozen=True)
class OrderBlock:
    """Deterministic demand/supply zone created by a directional displacement event."""

    direction: StructureDirection
    high: float
    low: float
    origin_timestamp: str
    confirmation_timestamp: str
    associated_structure_event: str = "break_of_structure"
    displacement: float = 0.0
    mitigation_status: str = "ACTIVE"
    invalidation_status: str = "VALID"
    version: str = "v0.1"
    source_index: int | None = None
    confirmation_index: int | None = None


@dataclass(frozen=True)
class BreakerBlock:
    """Existing zone that flips directional interpretation after a failure event."""

    origin_zone: OrderBlock
    original_direction: StructureDirection
    failure_event: str
    new_direction: StructureDirection
    high: float
    low: float
    status: str = "ACTIVE"
    transition_timestamp: str | None = None


@dataclass(frozen=True)
class DisplacementEvent:
    """Directional displacement with explicit detector-strength metadata."""

    direction: StructureDirection
    timestamp: str
    magnitude: float
    atr_multiple: float
    body_ratio: float
    structure_broken: bool
    confidence: float
    confirmation_index: int | None = None


@dataclass(frozen=True)
class PremiumDiscountState:
    """Deterministic price-location context relative to a recent dealing range."""

    range_high: float
    range_low: float
    equilibrium: float
    premium_zone: tuple[float, float]
    discount_zone: tuple[float, float]
    location: PriceLocation = PriceLocation.UNKNOWN
    timeframe: str = "5m"


@dataclass(frozen=True)
class SessionContext:
    """Simple deterministic session state for intraday XAUUSD analysis."""

    session: SessionName
    session_open: str | None = None
    session_high: float | None = None
    session_low: float | None = None
    previous_session_high: float | None = None
    previous_session_low: float | None = None
    timezone_name: str = "UTC"


@dataclass(frozen=True)
class StrategyConditionResult:
    """Condition-by-condition output for deterministic strategy evaluation."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class StrategyDefinition:
    """Small strategy descriptor with deterministic requirements and outputs."""

    strategy_id: str
    strategy_version: str
    required_features: tuple[str, ...] = ()
    confirmation_rules: tuple[str, ...] = ()
    invalidation_rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradeSetup:
    """Deterministic trade candidate produced by a strategy evaluator."""

    strategy_id: str
    strategy_version: str
    direction: StructureDirection
    confidence: float = 0.0
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    status: str = "INVALID"
    conditions: tuple[StrategyConditionResult, ...] = ()
    required_features: tuple[str, ...] = ()


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


def _to_utc_datetime(value: str) -> datetime:
    raw = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
        if require_confirmation and len(future_window) < lookback:
            # A pivot at the tail is not confirmed until all required right-side
            # candles have closed.
            continue
        future_high = max((c.high for c in future_window), default=current.high)
        future_low = min((c.low for c in future_window), default=current.low)
        confirmation_index = idx + lookback if require_confirmation else None

        if current.high > left_high and (not require_confirmation or current.high > future_high):
            swings.append(
                SwingPoint(
                    index=idx,
                    timestamp=current.timestamp,
                    kind="high",
                    price=float(current.high),
                    confirmed=require_confirmation,
                    confirmation_index=confirmation_index,
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
                    confirmation_index=confirmation_index,
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

    base = MarketStructureState(
        last_swing_high=last_high,
        last_swing_low=last_low,
        previous_swing_high=previous_high,
        previous_swing_low=previous_low,
        direction=direction,
    )
    session = detect_session_context(items)
    if session is not None:
        return MarketStructureState(
            last_swing_high=base.last_swing_high,
            last_swing_low=base.last_swing_low,
            previous_swing_high=base.previous_swing_high,
            previous_swing_low=base.previous_swing_low,
            direction=base.direction,
            session=session.session,
            session_open=session.session_open,
            session_high=session.session_high,
            session_low=session.session_low,
            previous_session_high=session.previous_session_high,
            previous_session_low=session.previous_session_low,
        )
    return base


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
        prior_swings = find_swing_points(
            prior, lookback=lookback, require_confirmation=True
        )
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
                confirmation_index=idx,
            )

        if prior_lows and prev.close >= prior_lows[-1] and curr.close < prior_lows[-1]:
            return BreakOfStructure(
                detected=True,
                direction=StructureDirection.BEARISH,
                broken_level=float(prior_lows[-1]),
                confirmation_timestamp=curr.timestamp,
                confirmation_index=idx,
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
        prior_swings = find_swing_points(
            history, lookback=lookback, require_confirmation=True
        )
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
                sweep_index=idx,
                confirmation_index=idx + 1,
            )

        # A sweep must actually trade through the level on either side; do not
        # apply a price-relative tolerance to only bearish setups.
        if current.high >= resistance and nxt.close < resistance:
            return LiquiditySweep(
                detected=True,
                direction=StructureDirection.BEARISH,
                swept_level=float(resistance),
                timestamp=nxt.timestamp,
                sweep_index=idx,
                confirmation_index=idx + 1,
            )

    return None


def detect_fvg(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    tolerance: float = 0.0,
    timeframe: str = "5m",
) -> list[FairValueGap]:
    """Three-candle fair value gap detector.

    A bullish FVG is defined as the middle candle's high being below the current
    candle's low after a higher-lows expansion. A bearish FVG is the mirror of
    that condition.
    """
    items = _coerce_candles(candles)
    gaps: list[FairValueGap] = []
    for idx in range(2, len(items)):
        left = items[idx - 2]
        current = items[idx]
        if left.high < current.low - tolerance:
            low = float(left.high)
            high = float(current.low)
            gaps.append(
                FairValueGap(
                    direction=StructureDirection.BULLISH,
                    low=low,
                    high=high,
                    created_at=current.timestamp,
                    timestamp=current.timestamp,
                    formation_index=idx - 1,
                    confirmation_index=idx,
                    timeframe=timeframe,
                    size=abs(high - low),
                )
            )
        elif left.low > current.high + tolerance:
            low = float(current.high)
            high = float(left.low)
            gaps.append(
                FairValueGap(
                    direction=StructureDirection.BEARISH,
                    low=low,
                    high=high,
                    created_at=current.timestamp,
                    timestamp=current.timestamp,
                    formation_index=idx - 1,
                    confirmation_index=idx,
                    timeframe=timeframe,
                    size=abs(high - low),
                )
            )
    return gaps


def detect_ifvg(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    tolerance: float = 0.0,
) -> list[InverseFairValueGap]:
    """Explicit inverse-FVG transition detector for a later imbalance reversal."""
    items = _coerce_candles(candles)
    if len(items) < 3:
        return []
    gaps = detect_fvg(items, tolerance=tolerance)
    transitions: list[InverseFairValueGap] = []
    for idx in range(1, len(gaps)):
        prior = gaps[idx - 1]
        current = gaps[idx]
        if prior.direction == StructureDirection.BULLISH and current.direction == StructureDirection.BEARISH:
            transitions.append(
                InverseFairValueGap(
                    original_direction=prior.direction,
                    new_direction=current.direction,
                    original_low=prior.low,
                    original_high=prior.high,
                    new_low=current.low,
                    new_high=current.high,
                    transition_timestamp=current.timestamp,
                    status="ACTIVE",
                )
            )
        elif prior.direction == StructureDirection.BEARISH and current.direction == StructureDirection.BULLISH:
            transitions.append(
                InverseFairValueGap(
                    original_direction=prior.direction,
                    new_direction=current.direction,
                    original_low=prior.low,
                    original_high=prior.high,
                    new_low=current.low,
                    new_high=current.high,
                    transition_timestamp=current.timestamp,
                    status="ACTIVE",
                )
            )
    return transitions


def detect_order_blocks(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    min_displacement: float | None = None,
    atr_period: int = 14,
    min_atr_multiple: float = 1.0,
) -> list[OrderBlock]:
    """Candidate order blocks filtered by ATR-normalized displacement.

    ``min_displacement`` remains available as an explicit absolute-price override
    for callers that need legacy behavior. The default uses ``min_atr_multiple``
    so the threshold scales across instruments and price levels.
    """
    items = _coerce_candles(candles)
    blocks: list[OrderBlock] = []
    # An absolute override needs no pre-impulse ATR history, so preserve the
    # legacy two-candle candidate at idx=1. The default normalized path starts
    # at idx=2 because ATR needs at least one completed pre-impulse range.
    start_idx = 1 if min_displacement is not None else 2
    for idx in range(start_idx, len(items)):
        previous = items[idx - 1]
        current = items[idx]
        displacement = abs(current.close - previous.close)
        if min_displacement is not None:
            qualifies = displacement >= min_displacement
        else:
            # Measure the impulse against volatility known before that impulse.
            history = items[:idx]
            period = min(atr_period, len(history) - 1)
            atr = calculate_atr(history, period=period) if period > 0 else None
            qualifies = bool(atr and atr.atr and atr.atr > 0 and displacement / atr.atr >= min_atr_multiple)
        if not qualifies:
            continue
        if current.close > previous.close:
            direction = StructureDirection.BULLISH
            high = max(current.high, previous.high)
            low = min(current.low, previous.low)
        else:
            direction = StructureDirection.BEARISH
            high = max(current.high, previous.high)
            low = min(current.low, previous.low)
        blocks.append(
            OrderBlock(
                direction=direction,
                high=float(high),
                low=float(low),
                origin_timestamp=previous.timestamp,
                confirmation_timestamp=current.timestamp,
                source_index=idx - 1,
                confirmation_index=idx,
                associated_structure_event="break_of_structure" if detect_break_of_structure(items[: idx + 1]) else "liquidity_sweep",
                displacement=float(displacement),
            )
        )
    return blocks


def detect_breaker_blocks(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    min_displacement: float | None = None,
    atr_period: int = 14,
    min_atr_multiple: float = 1.0,
) -> list[BreakerBlock]:
    """Transition of an existing order block into a new directional interpretation."""
    items = _coerce_candles(candles)
    blocks = detect_order_blocks(
        items,
        min_displacement=min_displacement,
        atr_period=atr_period,
        min_atr_multiple=min_atr_multiple,
    )
    breaker_blocks: list[BreakerBlock] = []
    for block in blocks:
        confirmed_at = next(
            (idx for idx, candle in enumerate(items) if candle.timestamp == block.confirmation_timestamp),
            -1,
        )
        subsequent = items[confirmed_at + 1:]
        if block.direction == StructureDirection.BULLISH:
            for candle in subsequent:
                if candle.close < block.low:
                    breaker_blocks.append(
                        BreakerBlock(
                            origin_zone=block,
                            original_direction=block.direction,
                            failure_event="close_below_order_block",
                            new_direction=StructureDirection.BEARISH,
                            high=block.high,
                            low=block.low,
                            transition_timestamp=candle.timestamp,
                        )
                    )
                    break
        else:
            for candle in subsequent:
                if candle.close > block.high:
                    breaker_blocks.append(
                        BreakerBlock(
                            origin_zone=block,
                            original_direction=block.direction,
                            failure_event="close_above_order_block",
                            new_direction=StructureDirection.BULLISH,
                            high=block.high,
                            low=block.low,
                            transition_timestamp=candle.timestamp,
                        )
                    )
                    break
    return breaker_blocks


def detect_displacement(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    atr_period: int = 14,
    threshold: float = 1.5,
) -> DisplacementEvent | None:
    """Directional displacement event defined by ATR-normalized move and a structure break."""
    items = _coerce_candles(candles)
    if len(items) < 2:
        return None
    atr = calculate_atr(items[-max(2, atr_period):], period=min(atr_period, max(2, len(items) - 1)))
    if atr is None or atr.atr is None or atr.atr <= 0:
        return None
    previous = items[-2]
    current = items[-1]
    magnitude = abs(current.close - previous.close)
    atr_multiple = magnitude / atr.atr
    if atr_multiple < threshold:
        return None
    direction = StructureDirection.BULLISH if current.close >= previous.close else StructureDirection.BEARISH
    body_ratio = abs(current.close - current.open) / max(current.high - current.low, 1e-9)
    structure_broken = detect_break_of_structure(items) is not None
    confidence = min(1.0, atr_multiple / (threshold * 2.0))
    return DisplacementEvent(
        direction=direction,
        timestamp=current.timestamp,
        magnitude=float(magnitude),
        atr_multiple=float(atr_multiple),
        body_ratio=float(body_ratio),
        structure_broken=structure_broken,
        confidence=float(confidence),
        confirmation_index=len(items) - 1,
    )


def calculate_premium_discount(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    lookback: int = 20,
    timeframe: str = "5m",
) -> PremiumDiscountState | None:
    """Range-relative premium/discount context with explicit equilibrium."""
    items = _coerce_candles(candles)
    if not items:
        return None
    window = items[-lookback:] if len(items) > lookback else items
    range_high = max(c.high for c in window)
    range_low = min(c.low for c in window)
    equilibrium = (range_high + range_low) / 2.0
    last_close = float(items[-1].close)
    if last_close >= equilibrium:
        location = PriceLocation.PREMIUM if last_close > equilibrium else PriceLocation.EQUILIBRIUM
    else:
        location = PriceLocation.DISCOUNT
    return PremiumDiscountState(
        range_high=float(range_high),
        range_low=float(range_low),
        equilibrium=float(equilibrium),
        premium_zone=(float(equilibrium), float(range_high)),
        discount_zone=(float(range_low), float(equilibrium)),
        location=location,
        timeframe=timeframe,
    )


def detect_session_context(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    timezone_name: str = "UTC",
) -> SessionContext | None:
    """Classify sessions in London/New York local time, including their DST shifts.

    Asia remains the configured UTC 00:00–08:00 window. London and New York
    are each configured as 08:00–17:00 local time; their intersection is the
    overlap session. The session label uses these local windows, while
    ``session_open``, ``session_high``, and ``session_low`` group candles by
    UTC calendar date. ``timezone_name`` is retained as output metadata.
    """
    items = _coerce_candles(candles)
    if not items:
        return None
    last_ts = _to_utc_datetime(items[-1].timestamp)
    london = last_ts.astimezone(pytz.timezone("Europe/London"))
    new_york = last_ts.astimezone(pytz.timezone("America/New_York"))
    london_open = 8 <= london.hour < 17
    new_york_open = 8 <= new_york.hour < 17
    if london_open and new_york_open:
        session = SessionName.LONDON_NEW_YORK_OVERLAP
    elif london_open:
        session = SessionName.LONDON
    elif new_york_open:
        session = SessionName.NEW_YORK
    elif 0 <= last_ts.hour < 8:
        session = SessionName.ASIA
    else:
        session = SessionName.OUTSIDE_CONFIGURED_SESSION

    session_items = [c for c in items if _to_utc_datetime(c.timestamp).date() == last_ts.date()]
    if not session_items:
        session_items = items

    session_open = session_items[0].timestamp
    session_high = max(c.high for c in session_items)
    session_low = min(c.low for c in session_items)
    previous_session = [c for c in items if _to_utc_datetime(c.timestamp).date() < last_ts.date()]
    previous_session_high = max((c.high for c in previous_session), default=None)
    previous_session_low = min((c.low for c in previous_session), default=None)
    return SessionContext(
        session=session,
        session_open=session_open,
        session_high=float(session_high),
        session_low=float(session_low),
        previous_session_high=float(previous_session_high) if previous_session_high is not None else None,
        previous_session_low=float(previous_session_low) if previous_session_low is not None else None,
        timezone_name=timezone_name,
    )


def detect_previous_levels(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    lookback_days: int = 1,
) -> dict[str, float | None]:
    """Previous day/week levels for a deterministic horizon-aware market state."""
    items = _coerce_candles(candles)
    if not items:
        return {"PDH": None, "PDL": None, "PWH": None, "PWL": None}
    recent = items[-max(1, lookback_days * 24 * 60):]
    pdh = max(c.high for c in recent)
    pdl = min(c.low for c in recent)
    return {"PDH": float(pdh), "PDL": float(pdl), "PWH": float(pdh), "PWL": float(pdl)}


def build_strategy_registry() -> dict[str, StrategyDefinition]:
    """Minimal registry for small, deterministic XAUUSD candidate strategies."""
    return {
        "LIQUIDITY_SWEEP_FVG_REVERSAL": StrategyDefinition(
            strategy_id="LIQUIDITY_SWEEP_FVG_REVERSAL",
            strategy_version="v0.1",
            required_features=("liquidity_sweep", "fair_value_gap"),
            confirmation_rules=("sweep_reclaimed", "directional_fvg"),
            invalidation_rules=("close_beyond_fvg_and_sweep_stop",),
        ),
        "LIQUIDITY_SWEEP_ORDER_BLOCK_REVERSAL": StrategyDefinition(
            strategy_id="LIQUIDITY_SWEEP_ORDER_BLOCK_REVERSAL",
            strategy_version="v0.1",
            required_features=("liquidity_sweep", "order_block"),
            confirmation_rules=("sweep_reclaimed", "directional_order_block", "matching_structure_break"),
            invalidation_rules=("close_beyond_order_block_and_sweep_stop",),
        ),
    }


def evaluate_strategy(
    candles: Sequence[Candle] | Iterable[Candle] | None,
    *,
    strategy_id: str = "LIQUIDITY_SWEEP_FVG_REVERSAL",
) -> TradeSetup:
    """Evaluate the requested registered strategy and derive levels from its structure."""
    items = _coerce_candles(candles)
    registry = build_strategy_registry()
    definition = registry.get(strategy_id)
    if definition is None:
        return TradeSetup(strategy_id=strategy_id, strategy_version="unknown", direction=StructureDirection.UNKNOWN)
    sweep = detect_liquidity_sweep(items)
    gaps = detect_fvg(items)
    order_blocks = detect_order_blocks(items)
    structure = detect_break_of_structure(items)
    direction = sweep.direction if sweep is not None else StructureDirection.UNKNOWN
    directional_gaps = [gap for gap in gaps if gap.direction == direction]
    directional_blocks = [block for block in order_blocks if block.direction == direction]
    feature_values = {
        "liquidity_sweep": sweep is not None,
        "fair_value_gap": bool(directional_gaps),
        "order_block": bool(directional_blocks),
    }
    conditions: list[StrategyConditionResult] = [
        StrategyConditionResult("Liquidity Sweep", sweep is not None, "reclaimed swept level" if sweep else "no confirmed sweep")
    ]
    for feature in definition.required_features:
        if feature == "liquidity_sweep":
            continue
        conditions.append(StrategyConditionResult(feature, feature_values.get(feature, False), "direction must match sweep"))
    for rule in definition.confirmation_rules:
        if rule == "sweep_reclaimed":
            passed = sweep is not None
        elif rule == "directional_fvg":
            passed = bool(directional_gaps)
        elif rule == "directional_order_block":
            passed = bool(directional_blocks)
        elif rule == "matching_structure_break":
            passed = structure is not None and structure.direction == direction
        else:
            passed = False
        conditions.append(StrategyConditionResult(rule, passed))

    invalidated = False
    if strategy_id == "LIQUIDITY_SWEEP_FVG_REVERSAL":
        candidate_zone = directional_gaps[-1] if directional_gaps else None
    else:
        candidate_zone = directional_blocks[-1] if directional_blocks else None
    entry = stop = target = None
    if sweep is not None and candidate_zone is not None and items:
        entry = (candidate_zone.low + candidate_zone.high) / 2.0
        stop = min(sweep.swept_level, candidate_zone.low) if direction == StructureDirection.BULLISH else max(sweep.swept_level, candidate_zone.high)
        close = items[-1].close
        invalidated = close <= stop if direction == StructureDirection.BULLISH else close >= stop
        prior_swings = find_swing_points(items[:-1], require_confirmation=True)
        opposing = [point.price for point in prior_swings if point.kind == ("high" if direction == StructureDirection.BULLISH else "low")]
        beyond = [level for level in opposing if (level > entry if direction == StructureDirection.BULLISH else level < entry)]
        target = (min(beyond) if direction == StructureDirection.BULLISH else max(beyond)) if beyond else None
    for rule in definition.invalidation_rules:
        conditions.append(StrategyConditionResult(rule, not invalidated, "active" if not invalidated else "last close crossed structural stop"))
    valid = (all(feature_values.get(feature, False) for feature in definition.required_features)
             and all(item.passed for item in conditions if item.name in definition.confirmation_rules)
             and not invalidated and entry is not None and stop is not None and target is not None)
    passed = sum(item.passed for item in conditions)
    return TradeSetup(
        strategy_id=strategy_id,
        strategy_version=definition.strategy_version,
        direction=direction,
        confidence=min(1.0, passed / max(1, len(conditions))),
        entry=float(entry) if entry is not None else None,
        stop=float(stop) if stop is not None else None,
        target=float(target) if target is not None else None,
        status="VALID" if valid else "INVALID",
        conditions=tuple(conditions),
        required_features=definition.required_features,
    )


__all__ = [
    "BreakOfStructure",
    "BreakerBlock",
    "DisplacementEvent",
    "FairValueGap",
    "InverseFairValueGap",
    "LiquiditySweep",
    "MarketStructureState",
    "OrderBlock",
    "PriceLocation",
    "PremiumDiscountState",
    "SessionContext",
    "SessionName",
    "StrategyConditionResult",
    "StrategyDefinition",
    "StructureDirection",
    "SwingPoint",
    "TradeSetup",
    "build_strategy_registry",
    "calculate_premium_discount",
    "compute_market_structure",
    "detect_break_of_structure",
    "detect_breaker_blocks",
    "detect_displacement",
    "detect_fvg",
    "detect_ifvg",
    "detect_liquidity_sweep",
    "detect_order_blocks",
    "detect_previous_levels",
    "detect_session_context",
    "evaluate_strategy",
    "find_swing_points",
]
