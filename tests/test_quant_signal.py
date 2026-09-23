import pytest
from pydantic import ValidationError

from tradingagents.graph.signal_processing import QuantSignal, SignalDirection, SignalSetupType


@pytest.mark.unit
class TestQuantSignalContract:
    def test_valid_long_signal(self):
        signal = QuantSignal(
            symbol="XAUUSD",
            timeframe="5m",
            direction=SignalDirection.LONG,
            setup_type=SignalSetupType.LIQUIDITY_SWEEP_REVERSAL,
            strength=0.82,
            reasons=["liquidity_sweep_detected", "support_respected"],
            valid=True,
        )
        assert signal.valid is True
        assert signal.direction == SignalDirection.LONG
        assert signal.strength == 0.82
        assert signal.setup_type == SignalSetupType.LIQUIDITY_SWEEP_REVERSAL

    def test_valid_short_signal(self):
        signal = QuantSignal(
            symbol="XAUUSD",
            timeframe="15m",
            direction=SignalDirection.SHORT,
            setup_type=SignalSetupType.CONFIRMED_REVERSAL,
            strength=0.91,
            reasons=["break_of_structure", "rejection_candle"],
            valid=True,
        )
        assert signal.valid is True
        assert signal.direction == SignalDirection.SHORT
        assert signal.strength == 0.91

    def test_none_direction_represents_no_actionable_setup(self):
        signal = QuantSignal(
            symbol="XAUUSD",
            timeframe="5m",
            direction=SignalDirection.NONE,
            setup_type=SignalSetupType.NONE,
            strength=0.0,
            reasons=["NO VALID SIGNAL"],
            valid=True,
        )
        assert signal.valid is True
        assert signal.direction == SignalDirection.NONE
        assert signal.strength == 0.0

    def test_invalid_direction_fails_validation(self):
        with pytest.raises(ValidationError):
            QuantSignal(
                symbol="XAUUSD",
                timeframe="5m",
                direction="INVALID",
                setup_type=SignalSetupType.LIQUIDITY_SWEEP_REVERSAL,
                strength=0.5,
                reasons=["liquidity_sweep_detected"],
            )

    def test_missing_symbol_fails_closed(self):
        signal = QuantSignal.no_valid_signal()
        assert signal.valid is False
        assert signal.direction == SignalDirection.NONE
        assert signal.setup_type == SignalSetupType.NONE
        assert signal.strength == 0.0
        assert signal.reasons == ["NO VALID SIGNAL"]

    def test_missing_timeframe_fails_closed(self):
        with pytest.raises(ValueError):
            QuantSignal(
                symbol="XAUUSD",
                timeframe="",
                direction=SignalDirection.LONG,
                setup_type=SignalSetupType.CONFIRMED_REVERSAL,
                strength=0.5,
                reasons=["support_respected"],
            )

    def test_invalid_strength_fails_validation(self):
        with pytest.raises(ValueError):
            QuantSignal(
                symbol="XAUUSD",
                timeframe="5m",
                direction=SignalDirection.LONG,
                setup_type=SignalSetupType.CONFIRMED_REVERSAL,
                strength=1.5,
                reasons=["support_respected"],
            )

    def test_missing_setup_type_fails_closed(self):
        with pytest.raises(ValueError):
            QuantSignal(
                symbol="XAUUSD",
                timeframe="5m",
                direction=SignalDirection.LONG,
                setup_type=None,
                strength=0.5,
                reasons=["support_respected"],
            )

    def test_empty_reasons_are_explicitly_invalid(self):
        with pytest.raises(ValueError):
            QuantSignal(
                symbol="XAUUSD",
                timeframe="5m",
                direction=SignalDirection.LONG,
                setup_type=SignalSetupType.LIQUIDITY_SWEEP_REVERSAL,
                strength=0.5,
                reasons=[],
            )
