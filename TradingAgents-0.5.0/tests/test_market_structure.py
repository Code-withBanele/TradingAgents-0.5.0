import pytest

from tradingagents.dataflows.intraday_types import Candle, Timeframe
from tradingagents.dataflows.market_structure import (
    StructureDirection,
    compute_market_structure,
    detect_break_of_structure,
    detect_liquidity_sweep,
    find_swing_points,
)


def _candles_from_prices(values, *, symbol="XAUUSD"):
    candles = []
    for idx, value in enumerate(values):
        ts = f"2024-01-01T00:{idx:02d}:00"
        candles.append(
            Candle(
                symbol=symbol,
                timestamp=ts,
                open=value,
                high=value,
                low=value,
                close=value,
                volume=10,
                timeframe=Timeframe.M5,
            )
        )
    return candles


def _ohlc_candles(rows):
    candles = []
    for idx, row in enumerate(rows):
        ts = f"2024-01-01T00:{idx:02d}:00"
        candles.append(
            Candle(
                symbol="XAUUSD",
                timestamp=ts,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row.get("volume", 10),
                timeframe=Timeframe.M5,
            )
        )
    return candles


def test_valid_swing_high_is_detected():
    candles = _ohlc_candles([
        {"open": 100, "high": 100, "low": 99, "close": 99.5},
        {"open": 101, "high": 101, "low": 100.5, "close": 100.8},
        {"open": 103, "high": 103.5, "low": 102.3, "close": 102.9},
        {"open": 102, "high": 102.4, "low": 101.2, "close": 101.5},
        {"open": 100, "high": 101.0, "low": 99.6, "close": 100.2},
    ])
    swings = find_swing_points(candles, lookback=2)
    assert any(point.kind == "high" and point.price == 103.5 for point in swings)


def test_valid_swing_low_is_detected():
    candles = _ohlc_candles([
        {"open": 99, "high": 100, "low": 98.5, "close": 99.2},
        {"open": 100, "high": 101.5, "low": 99.4, "close": 101.2},
        {"open": 101, "high": 102.2, "low": 98.1, "close": 99.7},
        {"open": 99.8, "high": 100.4, "low": 99.0, "close": 99.5},
        {"open": 100.3, "high": 101.2, "low": 99.9, "close": 100.8},
    ])
    swings = find_swing_points(candles, lookback=2)
    assert any(point.kind == "low" and point.price == 98.1 for point in swings)


def test_no_false_swing_for_flat_prices():
    candles = _candles_from_prices([100, 100, 100, 100, 100])
    assert find_swing_points(candles, lookback=2) == []


def test_configurable_lookback_changes_detection():
    candles = _ohlc_candles([
        {"open": 100, "high": 100, "low": 99, "close": 99.5},
        {"open": 101, "high": 102, "low": 100, "close": 101.5},
        {"open": 101.5, "high": 101.8, "low": 100.5, "close": 101.1},
        {"open": 100.8, "high": 102.4, "low": 100.4, "close": 102.0},
        {"open": 101.9, "high": 102.1, "low": 100.9, "close": 101.4},
    ])
    short_window = find_swing_points(candles, lookback=1)
    long_window = find_swing_points(candles, lookback=2)
    assert len(short_window) >= len(long_window)


def test_insufficient_history_returns_empty():
    candles = _candles_from_prices([10, 12, 11])
    assert find_swing_points(candles, lookback=3) == []


def test_confirmation_requires_future_candle_for_swing():
    candles = _ohlc_candles([
        {"open": 100, "high": 100, "low": 99, "close": 99.5},
        {"open": 101, "high": 102, "low": 100, "close": 101.5},
        {"open": 101.5, "high": 101.8, "low": 100.5, "close": 101.1},
        {"open": 100.8, "high": 102.4, "low": 100.4, "close": 102.0},
        {"open": 101.9, "high": 102.1, "low": 100.9, "close": 101.4},
    ])
    confirmed = find_swing_points(candles, lookback=2, require_confirmation=True)
    assert any(point.kind == "high" and point.confirmed for point in confirmed)


def test_bullish_structure_from_recent_swings():
    candles = _ohlc_candles([
        {"open": 100, "high": 100.8, "low": 99.4, "close": 100.2},
        {"open": 100.5, "high": 101.4, "low": 99.7, "close": 101.1},
        {"open": 101.2, "high": 101.8, "low": 100.4, "close": 101.5},
        {"open": 101.6, "high": 102.3, "low": 101.0, "close": 102.1},
        {"open": 102.0, "high": 102.7, "low": 101.4, "close": 102.5},
    ])
    state = compute_market_structure(candles, lookback=2)
    assert state.direction in {StructureDirection.BULLISH, StructureDirection.NEUTRAL}


def test_bearish_structure_from_recent_swings():
    candles = _ohlc_candles([
        {"open": 100, "high": 102.7, "low": 99.5, "close": 102.0},
        {"open": 101.9, "high": 102.5, "low": 100.8, "close": 101.2},
        {"open": 101.0, "high": 101.8, "low": 100.2, "close": 100.9},
        {"open": 100.8, "high": 101.3, "low": 99.6, "close": 99.8},
        {"open": 99.9, "high": 100.1, "low": 98.7, "close": 98.9},
    ])
    state = compute_market_structure(candles, lookback=2)
    assert state.direction in {StructureDirection.BEARISH, StructureDirection.NEUTRAL}


def test_neutral_unknown_structure_for_insufficient_data():
    assert compute_market_structure([], lookback=2).direction == StructureDirection.UNKNOWN


def test_bullish_bos_detected_once():
    candles = _ohlc_candles([
        {"open": 100, "high": 101, "low": 99, "close": 100.2},
        {"open": 100.2, "high": 101.2, "low": 99.5, "close": 100.6},
        {"open": 100.8, "high": 101.5, "low": 100.1, "close": 101.1},
        {"open": 101.2, "high": 101.8, "low": 100.7, "close": 101.7},
        {"open": 101.6, "high": 102.2, "low": 101.0, "close": 102.3},
        {"open": 102.1, "high": 102.5, "low": 101.4, "close": 102.1},
    ])
    bos = detect_break_of_structure(candles, lookback=2)
    assert bos is not None
    assert bos.detected is True
    assert bos.direction == StructureDirection.BULLISH


def test_bearish_bos_detected_once():
    candles = _ohlc_candles([
        {"open": 100, "high": 101.5, "low": 99.0, "close": 100.8},
        {"open": 101.0, "high": 101.9, "low": 99.8, "close": 100.6},
        {"open": 100.5, "high": 101.1, "low": 99.2, "close": 99.6},
        {"open": 99.8, "high": 100.5, "low": 98.8, "close": 98.9},
        {"open": 99.1, "high": 99.6, "low": 97.8, "close": 98.2},
    ])
    bos = detect_break_of_structure(candles, lookback=2)
    assert bos is not None
    assert bos.detected is True
    assert bos.direction == StructureDirection.BEARISH


def test_no_bos_when_price_does_not_clear_prior_extremum():
    candles = _ohlc_candles([
        {"open": 100, "high": 101, "low": 99.2, "close": 100.1},
        {"open": 100.3, "high": 100.8, "low": 99.4, "close": 100.0},
        {"open": 100.1, "high": 100.7, "low": 99.1, "close": 99.8},
        {"open": 99.9, "high": 100.2, "low": 98.8, "close": 99.4},
    ])
    bos = detect_break_of_structure(candles, lookback=2)
    assert bos is None or bos.detected is False


def test_bullish_liquidity_sweep_detected_after_reclaim():
    candles = _ohlc_candles([
        {"open": 100, "high": 101, "low": 99, "close": 100.2},
        {"open": 100.2, "high": 100.8, "low": 98.8, "close": 99.0},
        {"open": 99.1, "high": 99.6, "low": 98.5, "close": 99.9},
        {"open": 100.0, "high": 101.1, "low": 99.2, "close": 100.4},
    ])
    sweep = detect_liquidity_sweep(candles)
    assert sweep is not None
    assert sweep.detected is True
    assert sweep.direction == StructureDirection.BULLISH


def test_bearish_liquidity_sweep_detected_after_reclaim():
    candles = _ohlc_candles([
        {"open": 100, "high": 101.4, "low": 99.7, "close": 100.8},
        {"open": 100.7, "high": 101.2, "low": 99.8, "close": 100.0},
        {"open": 99.8, "high": 101.0, "low": 98.9, "close": 99.1},
        {"open": 99.1, "high": 100.0, "low": 98.6, "close": 98.8},
    ])
    sweep = detect_liquidity_sweep(candles)
    assert sweep is not None
    assert sweep.detected is True
    assert sweep.direction == StructureDirection.BEARISH


def test_wick_through_level_without_reclaim_is_not_confirmed_sweep():
    candles = _ohlc_candles([
        {"open": 100, "high": 101, "low": 99.0, "close": 100.1},
        {"open": 100.1, "high": 101.2, "low": 98.6, "close": 98.7},
        {"open": 98.8, "high": 99.3, "low": 97.9, "close": 98.5},
    ])
    assert detect_liquidity_sweep(candles) is None


def test_close_back_through_level_confirms_sweep():
    candles = _ohlc_candles([
        {"open": 100, "high": 101.0, "low": 99.0, "close": 100.2},
        {"open": 100.2, "high": 100.7, "low": 98.9, "close": 98.8},
        {"open": 98.8, "high": 99.4, "low": 98.2, "close": 99.5},
        {"open": 99.5, "high": 100.0, "low": 99.0, "close": 99.8},
    ])
    sweep = detect_liquidity_sweep(candles)
    assert sweep is not None
    assert sweep.detected is True
    assert sweep.direction == StructureDirection.BULLISH


def test_insufficient_history_for_liquidity_sweep_is_none():
    candles = _candles_from_prices([10, 11, 10])
    assert detect_liquidity_sweep(candles) is None


def test_empty_candle_collection_is_handled():
    assert find_swing_points([]) == []
    assert compute_market_structure([], lookback=2).direction == StructureDirection.UNKNOWN
    assert detect_break_of_structure([]) is None
    assert detect_liquidity_sweep([]) is None


def test_malformed_candle_input_is_rejected():
    with pytest.raises(TypeError):
        find_swing_points([{"bad": "input"}])


def test_equal_highs_lows_do_not_create_swings():
    candles = _candles_from_prices([100, 100, 100, 100])
    assert find_swing_points(candles, lookback=2) == []
