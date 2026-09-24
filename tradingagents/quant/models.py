"""Shared market-structure and signal-domain models.

These types live independently of detector implementations so compatibility
modules can re-export them without coupling model consumers to the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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


class DealingRangeSource(str, Enum):
    STRUCTURAL_RANGE = "STRUCTURAL_RANGE"
    SESSION_RANGE = "SESSION_RANGE"
    CUSTOM_RANGE = "CUSTOM_RANGE"


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
    protected_swing: SwingPoint | None = None


@dataclass(frozen=True)
class BreakOfStructure:
    """Structured break of the most recent swing level."""

    detected: bool
    direction: StructureDirection
    broken_level: float | None = None
    confirmation_timestamp: str | None = None
    confirmation_index: int | None = None
    structure_event_kind: str = "BOS"


# Legacy labels are normalized through this lookup; MSS and CISD have distinct
# deterministic definitions in this module and therefore are not aliases.
STRUCTURE_EVENT_ALIASES: dict[str, str] = {}
MSS_MIN_ATR_MULTIPLE = 1.5


@dataclass(frozen=True)
class InstrumentConfig:
    """Explicit caller-supplied instrument precision; no ticker inference is performed."""

    symbol: str | None = None
    pip_size: float = 0.0001
    price_decimals: int = 5
    tick_size: float | None = None
    minimum_price_increment: float | None = None
    quote_currency: str | None = None
    contract_metadata: tuple[tuple[str, str], ...] = ()
    provider_precision: int | None = None

    def __post_init__(self):
        if self.pip_size <= 0 or self.price_decimals < 0:
            raise ValueError("pip_size must be positive and price_decimals non-negative")
        if self.tick_size is not None and self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.provider_precision is not None and self.provider_precision < 0:
            raise ValueError("provider_precision must be non-negative")

    @classmethod
    def xauusd(cls, **overrides) -> InstrumentConfig:
        """Construct explicit common XAUUSD display/pip defaults; provider data may override."""
        values = {
            "symbol": "XAUUSD", "pip_size": 0.01, "price_decimals": 2,
            "tick_size": 0.01, "minimum_price_increment": 0.01,
        }
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=True)
class LiquidityPool:
    direction: StructureDirection
    level: float
    touch_indices: tuple[int, ...]
    swept: bool = False
    swept_index: int | None = None


@dataclass(frozen=True)
class CISDDefinition:
    """Versioned v1 rule: body close through the latest opposing candle open."""

    version: str = "cisd-v1"
    require_displacement: bool = False
    minimum_body_ratio: float = 0.5


@dataclass(frozen=True)
class CISDEvent:
    direction: StructureDirection
    level: float
    candidate_index: int
    confirmation_index: int | None
    status: str
    timestamp: str
    definition_version: str


@dataclass(frozen=True)
class ManipulationConfirmedBOS:
    """AMD-pattern structure: an initial BOS proven to be manipulation by a
    deeper sweep and reclaimed after a failed pullback.

    While pending, unavailable later-stage price fields are NaN and their
    indices are -1. Consumers must check ``status`` before using those fields.
    """

    direction: StructureDirection
    initial_break_level: float
    pre_break_level: float
    manipulation_extreme: float
    failed_pullback_level: float
    initial_break_index: int
    manipulation_extreme_index: int
    failed_pullback_index: int
    reclaim_index: int | None = None
    reclaim_timestamp: str | None = None
    status: str = "PENDING"
    invalidation_reason: str | None = None


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
    status: str = "CREATED"
    mitigation_status: str = "UNMITIGATED"
    invalidation_status: str = "VALID"
    formation_index: int | None = None
    confirmation_index: int | None = None
    mitigation_timestamp: str | None = None
    invalidation_timestamp: str | None = None


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
    definition_version: str = "displacement-v1"


@dataclass(frozen=True)
class DisplacementDefinition:
    version: str = "displacement-v1"
    minimum_atr_multiple: float = 1.5
    minimum_body_ratio: float = 0.5


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
    source: DealingRangeSource = DealingRangeSource.STRUCTURAL_RANGE
    range_start_timestamp: str | None = None
    range_end_timestamp: str | None = None


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
    session_start: str | None = None
    session_end: str | None = None


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
    timestamp: str | None = None
    timeframe: str = "5m"


__all__ = [
    "StructureDirection",
    "SessionName",
    "PriceLocation",
    "DealingRangeSource",
    "SwingPoint",
    "MarketStructureState",
    "BreakOfStructure",
    "InstrumentConfig",
    "LiquidityPool",
    "CISDDefinition",
    "CISDEvent",
    "ManipulationConfirmedBOS",
    "LiquiditySweep",
    "FairValueGap",
    "InverseFairValueGap",
    "OrderBlock",
    "BreakerBlock",
    "DisplacementEvent",
    "DisplacementDefinition",
    "PremiumDiscountState",
    "SessionContext",
    "StrategyConditionResult",
    "StrategyDefinition",
    "TradeSetup",
    "STRUCTURE_EVENT_ALIASES",
    "MSS_MIN_ATR_MULTIPLE",
]
