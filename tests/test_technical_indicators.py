import math

from tradingagents.dataflows.intraday_types import Candle, Timeframe
from tradingagents.dataflows.technical_indicators import (
    StochasticState,
    VolatilityResult,
    calculate_atr,
    calculate_stochastic,
    calculate_true_range,
    calculate_vwap,
)


def _candles(rows):
    candles = []
    for idx, row in enumerate(rows):
        candles.append(
            Candle(
                symbol="XAUUSD",
                timestamp=row["timestamp"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row.get("volume", 10),
                timeframe=Timeframe.M5,
            )
        )
    return candles


def test_stochastic_oversold_state():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 100.8, "low": 99.5, "close": 99.8},
            {"timestamp": "2024-01-01T00:05:00", "open": 99.9, "high": 100.6, "low": 99.4, "close": 99.6},
            {"timestamp": "2024-01-01T00:10:00", "open": 99.7, "high": 100.2, "low": 99.1, "close": 99.3},
            {"timestamp": "2024-01-01T00:15:00", "open": 99.4, "high": 99.9, "low": 98.8, "close": 98.9},
            {"timestamp": "2024-01-01T00:20:00", "open": 98.9, "high": 99.5, "low": 98.5, "close": 98.7},
        ]
    )
    result = calculate_stochastic(candles, k_period=3, d_period=2)
    assert result is not None
    assert result.state == StochasticState.OVERSOLD
    assert 0.0 <= result.k <= 100.0
    assert 0.0 <= result.d <= 100.0


def test_stochastic_overbought_state():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 99.0, "high": 99.2, "low": 98.7, "close": 99.1},
            {"timestamp": "2024-01-01T00:05:00", "open": 99.3, "high": 99.9, "low": 99.1, "close": 99.8},
            {"timestamp": "2024-01-01T00:10:00", "open": 99.7, "high": 100.6, "low": 99.3, "close": 100.5},
            {"timestamp": "2024-01-01T00:15:00", "open": 100.4, "high": 101.2, "low": 99.8, "close": 101.0},
            {"timestamp": "2024-01-01T00:20:00", "open": 100.9, "high": 101.5, "low": 100.2, "close": 101.4},
        ]
    )
    result = calculate_stochastic(candles, k_period=3, d_period=2)
    assert result is not None
    assert result.state == StochasticState.OVERBOUGHT


def test_stochastic_neutral_state_and_configurable_periods():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"timestamp": "2024-01-01T00:05:00", "open": 100.2, "high": 101.2, "low": 99.1, "close": 100.3},
            {"timestamp": "2024-01-01T00:10:00", "open": 100.4, "high": 101.4, "low": 99.3, "close": 100.2},
            {"timestamp": "2024-01-01T00:15:00", "open": 100.5, "high": 101.5, "low": 99.4, "close": 100.6},
            {"timestamp": "2024-01-01T00:20:00", "open": 100.7, "high": 101.1, "low": 99.6, "close": 100.4},
        ]
    )
    result = calculate_stochastic(candles, k_period=3, d_period=2)
    assert result is not None
    assert result.state == StochasticState.NEUTRAL


def test_stochastic_handles_insufficient_history_and_flat_range():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"timestamp": "2024-01-01T00:05:00", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
        ]
    )
    assert calculate_stochastic(candles, k_period=3, d_period=2) is None


def test_stochastic_is_deterministic_for_same_input():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"timestamp": "2024-01-01T00:05:00", "open": 100.5, "high": 101.5, "low": 99.5, "close": 101.2},
            {"timestamp": "2024-01-01T00:10:00", "open": 101.1, "high": 102.0, "low": 100.2, "close": 101.8},
            {"timestamp": "2024-01-01T00:15:00", "open": 101.7, "high": 102.4, "low": 100.8, "close": 102.2},
            {"timestamp": "2024-01-01T00:20:00", "open": 102.1, "high": 102.8, "low": 101.0, "close": 102.6},
        ]
    )
    first = calculate_stochastic(candles, k_period=3, d_period=2)
    second = calculate_stochastic(list(candles), k_period=3, d_period=2)
    assert first == second


def test_vwap_uses_cumulative_typical_price():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10},
            {"timestamp": "2024-01-01T00:05:00", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 20},
            {"timestamp": "2024-01-01T00:10:00", "open": 101.5, "high": 102.5, "low": 101.0, "close": 102.0, "volume": 30},
        ]
    )
    result = calculate_vwap(candles)
    assert result is not None
    expected_prices = [((101 + 99 + 100.5) / 3), ((102 + 100 + 101.5) / 3), ((102.5 + 101 + 102.0) / 3)]
    expected = (
        expected_prices[0] * 10 + expected_prices[1] * 20 + expected_prices[2] * 30
    ) / (10 + 20 + 30)
    assert math.isclose(result.vwap, expected, rel_tol=1e-9, abs_tol=1e-9)


def test_vwap_handles_session_reset_and_zero_volume():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10},
            {"timestamp": "2024-01-02T00:00:00", "open": 102.0, "high": 103.0, "low": 101.0, "close": 102.0, "volume": 20},
            {"timestamp": "2024-01-02T00:05:00", "open": 103.0, "high": 104.0, "low": 102.0, "close": 103.0, "volume": 0},
        ]
    )
    result = calculate_vwap(candles, reset_session=True)
    assert result is not None
    assert result.session_start == "2024-01-02"
    assert result.vwap == 102.0


def test_vwap_missing_and_zero_volume_handling():
    assert calculate_vwap([]) is None
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 0},
            {"timestamp": "2024-01-01T00:05:00", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 0},
        ]
    )
    assert calculate_vwap(candles) is None


def test_vwap_is_deterministic_for_same_input():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 15},
            {"timestamp": "2024-01-01T00:05:00", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 25},
        ]
    )
    first = calculate_vwap(candles)
    second = calculate_vwap(list(candles))
    assert first == second


def test_true_range_and_atr_basic_behaviour():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
            {"timestamp": "2024-01-01T00:05:00", "open": 100.8, "high": 105.0, "low": 98.0, "close": 101.0},
            {"timestamp": "2024-01-01T00:10:00", "open": 101.2, "high": 103.0, "low": 100.5, "close": 102.0},
            {"timestamp": "2024-01-01T00:15:00", "open": 101.8, "high": 102.5, "low": 100.0, "close": 100.8},
        ]
    )
    tr = calculate_true_range(candles[1], candles[0].close)
    assert tr == 7.0
    atr = calculate_atr(candles, period=2)
    assert atr is not None
    assert atr.true_range > 0
    assert atr.atr > 0
    assert atr.timestamp == candles[-1].timestamp


def test_true_range_handles_first_candle_and_flat_data():
    flat = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"timestamp": "2024-01-01T00:05:00", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
        ]
    )
    assert calculate_true_range(flat[0], None) == 0.0
    assert calculate_true_range(flat[1], flat[0].close) == 0.0
    assert calculate_atr(flat, period=2) is None


def test_true_range_is_deterministic_for_same_input():
    candles = _candles(
        [
            {"timestamp": "2024-01-01T00:00:00", "open": 100.0, "high": 101.0, "low": 98.5, "close": 99.0},
            {"timestamp": "2024-01-01T00:05:00", "open": 99.3, "high": 103.0, "low": 96.0, "close": 99.8},
            {"timestamp": "2024-01-01T00:10:00", "open": 99.7, "high": 102.0, "low": 98.0, "close": 100.4},
        ]
    )
    assert calculate_true_range(candles[1], candles[0].close) == calculate_true_range(candles[1], candles[0].close)
    atr = calculate_atr(candles, period=2)
    second = calculate_atr(list(candles), period=2)
    assert atr == second
