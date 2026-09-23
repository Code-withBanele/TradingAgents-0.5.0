"""Signal-processing boundary for the graph.

This module keeps the existing string-based rating API for the trading graph, and
adds a minimal quantitative signal contract for future strategy slices. The
quantitative contract is deliberately small: it describes a candidate setup,
never a broker action, and it fails closed on malformed input.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from tradingagents.agents.utils.rating import RATING_REVIEW, extract_rating


class SignalDirection(str, Enum):
    """Long/short/flat direction for a candidate setup."""

    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class SignalSetupType(str, Enum):
    """Minimal extensible set for deterministic quant-signal labels."""

    LIQUIDITY_SWEEP_REVERSAL = "LIQUIDITY_SWEEP_REVERSAL"
    CONFIRMED_REVERSAL = "CONFIRMED_REVERSAL"
    NONE = "NONE"


class QuantSignal(BaseModel):
    """Pure signal-layer object for a candidate market setup.

    This is intentionally not an execution object: it does not place trades,
    manage brokerage positions, or infer risk. It simply describes the
    candidate setup and whether it is actionable.
    """

    symbol: str | None = Field(default=None, description="Instrument symbol, e.g. XAUUSD")
    timeframe: str | None = Field(default=None, description="Timeframe label, e.g. 5m")
    direction: SignalDirection | None = Field(default=None, description="Signal direction")
    setup_type: SignalSetupType | None = Field(default=None, description="Candidate setup type")
    strength: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Normalized signal strength from 0.0 (no signal) to 1.0 (strongest candidate). "
            "This is not a win probability or guaranteed outcome; it is a bounded strength scalar."
        ),
    )
    reasons: list[str] = Field(default_factory=list, description="Structured reason codes")
    valid: bool = Field(default=True, description="Whether this represents a valid actionable signal")

    @field_validator("symbol", "timeframe")
    @classmethod
    def _validate_required_text(cls, value: str | None, info):
        if value is None:
            return value
        text = str(value).strip()
        if not text:
            raise ValueError(f"{info.field_name} cannot be empty")
        return text

    @field_validator("reasons")
    @classmethod
    def _validate_reasons(cls, value: list[str]):
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("reasons must be a list of strings")
            trimmed = item.strip()
            if not trimmed:
                raise ValueError("reasons cannot contain blank entries")
            cleaned.append(trimmed)
        if not cleaned:
            raise ValueError("reasons cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_signal_contract(self):
        if not self.valid:
            if self.direction is not None and self.direction != SignalDirection.NONE:
                raise ValueError("explicit no-signal sentinels must use direction NONE")
            if self.setup_type is not None and self.setup_type != SignalSetupType.NONE:
                raise ValueError("explicit no-signal sentinels must use setup type NONE")
            if self.strength not in (None, 0.0):
                raise ValueError("explicit no-signal sentinels must use strength 0.0")
            return self

        if not self.symbol or not self.timeframe:
            raise ValueError("symbol and timeframe are required for actionable signals")

        if self.direction is None:
            raise ValueError("direction is required for actionable signals")
        if self.setup_type is None:
            raise ValueError("setup_type is required for actionable signals")
        if self.strength is None:
            raise ValueError("strength is required for actionable signals")

        if self.direction == SignalDirection.NONE:
            if self.setup_type != SignalSetupType.NONE:
                raise ValueError("NONE direction requires NONE setup type")
            if self.strength != 0.0:
                raise ValueError("NONE direction requires a strength of 0.0")
            if not self.reasons:
                raise ValueError("NONE signals must include reasons")
            return self

        if self.setup_type == SignalSetupType.NONE:
            raise ValueError("Actionable signals require a concrete setup type")

        if self.direction not in (SignalDirection.LONG, SignalDirection.SHORT):
            raise ValueError("direction must be LONG or SHORT for actionable signals")

        if not 0.0 <= float(self.strength) <= 1.0:
            raise ValueError("strength must be between 0.0 and 1.0 inclusive")

        if not self.reasons:
            raise ValueError("actionable signals must include at least one reason")

        return self

    @classmethod
    def no_valid_signal(cls, *, reason: str = "NO VALID SIGNAL") -> "QuantSignal":
        """Construct a fail-closed no-signal sentinel.

        This is the structural representation of "NO VALID SIGNAL" and is used
        when the input is malformed or the broader strategy layer has not yet
        produced a valid candidate.
        """
        return cls(
            symbol=None,
            timeframe=None,
            direction=SignalDirection.NONE,
            setup_type=SignalSetupType.NONE,
            strength=0.0,
            reasons=[reason],
            valid=False,
        )


class SignalProcessor:
    """Read the 5-tier rating out of a Portfolio Manager decision."""

    def __init__(self, quick_thinking_llm: Any = None):
        # The LLM argument is accepted for backwards compatibility but ignored:
        # the PM's structured output guarantees the rating is parseable from the
        # rendered markdown without a second LLM call, so it is not stored.
        pass

    def process_signal(self, full_signal: str) -> str:
        """Return one of Buy / Overweight / Hold / Underweight / Sell, or REVIEW.

        An unrecognizable decision yields ``REVIEW`` rather than a fabricated
        ``Hold``, so a parsing failure is visible instead of masquerading as a
        tradeable neutral signal (#1170). Consumers that map the result onto the
        5-tier enum should guard with :func:`~tradingagents.agents.utils.rating.is_review`.
        """
        if not isinstance(full_signal, str):
            return RATING_REVIEW
        rating = extract_rating(full_signal)
        return rating if rating is not None else RATING_REVIEW

    def parse_quant_signal(self, payload: Any) -> QuantSignal:
        """Convert a quantitative payload into a validated QuantSignal.

        Malformed values fail closed and return the canonical ``NO VALID SIGNAL``
        representation instead of inferring a tradeable direction.
        """
        if isinstance(payload, QuantSignal):
            return payload
        if isinstance(payload, dict):
            try:
                return QuantSignal.model_validate(payload)
            except ValidationError:
                return QuantSignal.no_valid_signal()
        if payload is None:
            return QuantSignal.no_valid_signal()
        try:
            return QuantSignal.model_validate(payload)
        except ValidationError:
            return QuantSignal.no_valid_signal()


__all__ = [
    "QuantSignal",
    "SignalDirection",
    "SignalProcessor",
    "SignalSetupType",
]
