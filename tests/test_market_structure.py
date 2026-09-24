import pytest

from tradingagents.dataflows.intraday_types import Candle, Timeframe
from tradingagents.dataflows.market_structure import (
    BreakOfStructure,
    FairValueGap,
    LiquiditySweep,
    ManipulationConfirmedBOS,
    OrderBlock,
    SwingPoint,
    StructureDirection,
    compute_market_structure,
    detect_break_of_structure,
    detect_breaker_blocks,
    detect_fvg,
    detect_liquidity_sweep,
    detect_manipulation_confirmed_bos,
    detect_order_blocks,
    detect_session_context,
    evaluate_strategy,
    find_swing_points,
)
import tradingagents.dataflows.market_structure as market_structure


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


def _amd_candles(*, bearish=False, tail=True):
    rows = [
        (10, 11, 9, 10),
        (12, 13, 10, 12),
        (9, 12, 8, 9),
        (9.5, 10, 9, 9.5),
        (13.5, 14, 9.5, 13.5),
        (10, 12, 7, 10),
        (9, 11, 8, 9),
        (11, 12, 9, 11),
        (10, 11, 9, 10),
        (12.5, 13.5, 10, 12.5),
        (12, 15, 11, 14),
    ]
    if not tail:
        rows = rows[:7]
    if bearish:
        pivot = 20
        rows = [(2 * pivot - o, 2 * pivot - low, 2 * pivot - high, 2 * pivot - close) for o, high, low, close in rows]
    return _ohlc_candles([
        {"open": o, "high": high, "low": low, "close": close}
        for o, high, low, close in rows
    ])


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


@pytest.mark.parametrize("bearish", [False, True])
def test_manipulation_confirmed_bos_clean_sequence(bearish):
    result = detect_manipulation_confirmed_bos(_amd_candles(bearish=bearish), lookback=1)
    assert result is not None
    assert result.status == "CONFIRMED"
    assert result.initial_break_index < result.manipulation_extreme_index < result.failed_pullback_index < result.reclaim_index


def test_manipulation_confirmed_bos_invalidated_when_extreme_is_retaken():
    candles = _amd_candles()
    candles[8] = candles[8].model_copy(update={"low": 6.5, "close": 10.0, "open": 10.0})
    result = detect_manipulation_confirmed_bos(candles[:9], lookback=1)
    assert result is not None
    assert result.status == "INVALIDATED"
    assert result.invalidation_reason == "manipulation_extreme_retaken"


def test_manipulation_confirmed_bos_invalidated_when_prebreak_level_is_lost():
    candles = _amd_candles()
    candles[8] = candles[8].model_copy(update={"open": 8.0, "low": 7.5, "close": 7.8})
    result = detect_manipulation_confirmed_bos(candles[:9], lookback=1)
    assert result is not None
    assert result.status == "INVALIDATED"
    assert result.invalidation_reason == "pre_break_level_reclaimed_against"


def test_manipulation_confirmed_bos_invalidated_by_opposing_bos(monkeypatch):
    candles = _amd_candles()
    monkeypatch.setattr(
        market_structure,
        "_all_break_of_structure_events",
        lambda items, *, lookback: [
            BreakOfStructure(True, StructureDirection.BULLISH, 13.0, items[4].timestamp, 4),
            BreakOfStructure(True, StructureDirection.BEARISH, 10.0, items[7].timestamp, 7),
        ],
    )
    result = detect_manipulation_confirmed_bos(candles, lookback=1)
    assert result is not None
    assert result.status == "INVALIDATED"
    assert result.invalidation_reason == "opposing_bos_before_reclaim"


def test_manipulation_confirmed_bos_stays_pending_before_failed_pullback():
    result = detect_manipulation_confirmed_bos(_amd_candles(tail=False), lookback=1)
    assert result is not None
    assert result.status == "PENDING"
    assert result.manipulation_extreme_index == 5
    assert result.failed_pullback_index == -1


def test_liquidity_sweep_uses_most_recent_swing_not_highest_priced_swing(monkeypatch):
    candles = _ohlc_candles([
        {"open": 10, "high": 11, "low": 10, "close": 10},
        {"open": 10, "high": 11, "low": 9, "close": 10},
        {"open": 10, "high": 11, "low": 10, "close": 10},
        {"open": 10, "high": 11, "low": 10, "close": 10},
        {"open": 10, "high": 11, "low": 8, "close": 10},
        {"open": 10, "high": 11, "low": 9, "close": 10},
        {"open": 8, "high": 10, "low": 7.5, "close": 8},
        {"open": 8, "high": 9, "low": 8, "close": 8.5},
    ])
    swings = [
        SwingPoint(1, candles[1].timestamp, "low", 9.0, True, 2),
        SwingPoint(4, candles[4].timestamp, "low", 8.0, True, 5),
    ]
    irrelevant = [
        SwingPoint(0, candles[0].timestamp, "low", 0.0, True, 0),
        SwingPoint(0, candles[0].timestamp, "high", 100.0, True, 0),
    ]
    monkeypatch.setattr(market_structure, "find_swing_points", lambda items, **kwargs: swings if len(items) >= 6 else irrelevant)
    result = detect_liquidity_sweep(candles)
    assert result is not None
    assert result.direction == StructureDirection.BULLISH
    assert result.swept_level == 8.0
    assert result.sweep_index == 6


@pytest.mark.parametrize(
    ("bos_direction", "expected"),
    [
        (StructureDirection.BEARISH, "liquidity_sweep"),
        (StructureDirection.BULLISH, "break_of_structure"),
    ],
)
def test_order_block_event_requires_matching_direction_since_structural_swing(monkeypatch, bos_direction, expected):
    candles = _ohlc_candles([
        {"open": 10, "high": 11, "low": 9, "close": 10},
        {"open": 10, "high": 12, "low": 9, "close": 11},
        {"open": 11, "high": 13, "low": 10, "close": 12},
    ])
    monkeypatch.setattr(
        market_structure,
        "find_swing_points",
        lambda items, **kwargs: [SwingPoint(0, candles[0].timestamp, "high", 11, True, 0)],
    )
    monkeypatch.setattr(
        market_structure,
        "_all_break_of_structure_events",
        lambda items, *, lookback: [BreakOfStructure(True, bos_direction, 11, candles[1].timestamp, 1)],
    )
    blocks = detect_order_blocks(candles, min_displacement=0.1)
    assert blocks[-1].associated_structure_event == expected


def test_manipulation_confirmed_bos_strategy_is_registered_and_wired(monkeypatch):
    pattern = ManipulationConfirmedBOS(
        direction=StructureDirection.BULLISH,
        initial_break_level=13,
        pre_break_level=8,
        manipulation_extreme=7,
        failed_pullback_level=12,
        initial_break_index=4,
        manipulation_extreme_index=5,
        failed_pullback_index=7,
        reclaim_index=9,
        reclaim_timestamp="2024-01-01T00:09:00",
        status="CONFIRMED",
    )
    monkeypatch.setattr(market_structure, "detect_manipulation_confirmed_bos", lambda items: pattern)
    setup = evaluate_strategy(_amd_candles(), strategy_id="MANIPULATION_CONFIRMED_BOS")
    assert setup.strategy_version == "v0.1"
    assert setup.required_features == ("manipulation_confirmed_bos",)
    assert setup.entry == 11.75
    assert setup.stop == 7
    assert setup.status == "VALID"


def test_manipulation_confirmed_bos_strategy_handles_no_candidate():
    setup = evaluate_strategy(_candles_from_prices([10, 10, 10, 10]), strategy_id="MANIPULATION_CONFIRMED_BOS")
    assert setup.status == "INVALID"
    assert setup.direction == StructureDirection.UNKNOWN


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
        {"open": 101.4, "high": 101.9, "low": 100.8, "close": 101.2},
    ])
    confirmed = find_swing_points(candles, lookback=2, require_confirmation=True)
    high = next(point for point in confirmed if point.kind == "high")
    assert high.confirmed
    assert high.confirmation_index == high.index + 2


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
        {"open": 99.5, "high": 100, "low": 99, "close": 99.5},
        {"open": 100, "high": 101, "low": 99.5, "close": 100.5},
        {"open": 101, "high": 103, "low": 100, "close": 102},
        {"open": 102, "high": 102, "low": 100.2, "close": 101},
        {"open": 101, "high": 101.8, "low": 100.5, "close": 101.5},
        {"open": 101.5, "high": 104, "low": 101, "close": 103.5},
    ])
    bos = detect_break_of_structure(candles, lookback=2)
    assert bos is not None
    assert bos.detected is True
    assert bos.direction == StructureDirection.BULLISH
    assert bos.confirmation_index == 5


def test_bearish_bos_detected_once():
    candles = _ohlc_candles([
        {"open": 100.5, "high": 101.5, "low": 100, "close": 100.5},
        {"open": 100.5, "high": 101.9, "low": 99.8, "close": 100.6},
        {"open": 100.5, "high": 101.1, "low": 97, "close": 98},
        {"open": 98, "high": 100.5, "low": 98.8, "close": 99},
        {"open": 99, "high": 99.6, "low": 98.2, "close": 98.5},
        {"open": 98.5, "high": 99, "low": 96, "close": 96.5},
    ])
    bos = detect_break_of_structure(candles, lookback=2)
    assert bos is not None
    assert bos.detected is True
    assert bos.direction == StructureDirection.BEARISH
    assert bos.confirmation_index == 5


def test_bos_does_not_use_a_swing_before_its_confirmation_bar():
    candles = _ohlc_candles([
        {"open": 99.5, "high": 100, "low": 99, "close": 99.5},
        {"open": 99.5, "high": 101, "low": 99.2, "close": 100.5},
        {"open": 100.5, "high": 103, "low": 100, "close": 102},
        {"open": 102, "high": 104, "low": 101, "close": 103.5},
    ])
    assert detect_break_of_structure(candles, lookback=1) is None


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
        {"open": 99.8, "high": 101.3, "low": 98.9, "close": 99.1},
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
    assert sweep.sweep_index == 1
    assert sweep.confirmation_index == 2


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


def test_breaker_blocks_accept_one_shot_iterables():
    candles = _ohlc_candles([
        {"open": 99.5, "high": 100, "low": 99, "close": 99.5},
        {"open": 99.5, "high": 101, "low": 99.2, "close": 100.5},
        {"open": 100.5, "high": 105, "low": 100, "close": 104.5},
        {"open": 100, "high": 101, "low": 98, "close": 98.5},
    ])
    expected = detect_breaker_blocks(candles, min_displacement=0)
    actual = detect_breaker_blocks((candle for candle in candles), min_displacement=0)
    assert actual == expected
    assert actual


def test_bearish_sweep_requires_actual_resistance_cross():
    candles = _ohlc_candles([
        {"open": 99, "high": 100, "low": 98, "close": 99},
        {"open": 99, "high": 99.9, "low": 98.5, "close": 99.2},
        {"open": 99.2, "high": 99.7, "low": 98.6, "close": 99.1},
        {"open": 99.1, "high": 99.3, "low": 98.8, "close": 99.0},
    ])
    assert detect_liquidity_sweep(candles) is None


def test_bullish_sweep_requires_actual_support_cross():
    candles = _ohlc_candles([
        {"open": 101, "high": 102, "low": 100, "close": 101},
        {"open": 101, "high": 101.8, "low": 100.2, "close": 101},
        {"open": 101, "high": 101.5, "low": 100.3, "close": 101.1},
        {"open": 101.1, "high": 101.3, "low": 100.5, "close": 101.2},
    ])
    assert detect_liquidity_sweep(candles) is None


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2024-03-08T12:30:00Z", "LONDON"),
        ("2024-03-11T12:30:00Z", "LONDON_NEW_YORK_OVERLAP"),
        ("2024-03-29T07:30:00Z", "ASIA"),
        ("2024-04-01T07:30:00Z", "LONDON"),
        ("2024-10-25T07:30:00Z", "LONDON"),
        ("2024-10-28T07:30:00Z", "ASIA"),
        ("2024-11-01T12:30:00Z", "LONDON_NEW_YORK_OVERLAP"),
        ("2024-11-04T12:30:00Z", "LONDON"),
    ],
)
def test_session_classification_at_us_and_uk_dst_boundaries(timestamp, expected):
    template = _ohlc_candles([{"open": 1, "high": 2, "low": 0, "close": 1}])[0]
    candle = template.model_copy(update={"timestamp": timestamp})
    context = detect_session_context([candle])
    assert context.session.value == expected


def test_strategy_registry_requirements_drive_evaluation():
    candles = _candles_from_prices([100, 101, 99, 102])
    fvg_setup = evaluate_strategy(candles, strategy_id="LIQUIDITY_SWEEP_FVG_REVERSAL")
    block_setup = evaluate_strategy(candles, strategy_id="LIQUIDITY_SWEEP_ORDER_BLOCK_REVERSAL")
    assert fvg_setup.required_features == ("liquidity_sweep", "fair_value_gap")
    assert block_setup.required_features == ("liquidity_sweep", "order_block")
    assert {condition.name for condition in fvg_setup.conditions} != {
        condition.name for condition in block_setup.conditions
    }


def test_fvg_strategy_rejects_required_gap_in_wrong_direction(monkeypatch):
    monkeypatch.setattr(
        market_structure,
        "detect_liquidity_sweep",
        lambda _: LiquiditySweep(True, StructureDirection.BULLISH, 100, "2024-01-01T00:00:00Z"),
    )
    monkeypatch.setattr(
        market_structure,
        "detect_fvg",
        lambda _: [FairValueGap(StructureDirection.BEARISH, 99, 100, "t", "t")],
    )
    setup = evaluate_strategy([], strategy_id="LIQUIDITY_SWEEP_FVG_REVERSAL")
    gap_condition = next(item for item in setup.conditions if item.name == "fair_value_gap")
    assert not gap_condition.passed
    assert setup.status == "INVALID"


def test_order_block_strategy_rejects_required_block_in_wrong_direction(monkeypatch):
    monkeypatch.setattr(
        market_structure,
        "detect_liquidity_sweep",
        lambda _: LiquiditySweep(True, StructureDirection.BULLISH, 100, "2024-01-01T00:00:00Z"),
    )
    monkeypatch.setattr(market_structure, "detect_fvg", lambda _: [])
    monkeypatch.setattr(
        market_structure,
        "detect_order_blocks",
        lambda _: [OrderBlock(StructureDirection.BEARISH, 101, 99, "a", "b")],
    )
    setup = evaluate_strategy([], strategy_id="LIQUIDITY_SWEEP_ORDER_BLOCK_REVERSAL")
    block_condition = next(item for item in setup.conditions if item.name == "order_block")
    assert not block_condition.passed
    assert setup.status == "INVALID"


def test_absolute_order_block_threshold_allows_first_candidate_pair():
    candles = _ohlc_candles([
        {"open": 100, "high": 101, "low": 99, "close": 100},
        {"open": 100, "high": 102, "low": 99.5, "close": 101},
    ])
    blocks = detect_order_blocks(candles, min_displacement=0.5)
    assert len(blocks) == 1
    assert blocks[0].source_index == 0
    assert blocks[0].confirmation_index == 1


def test_fvg_is_available_only_at_third_candle_close():
    candles = _ohlc_candles([
        {"open": 100, "high": 101, "low": 99, "close": 100},
        {"open": 101, "high": 103, "low": 100, "close": 102},
        {"open": 103, "high": 104, "low": 102, "close": 103.5},
    ])
    gap = detect_fvg(candles)[0]
    assert gap.formation_index == 1
    assert gap.confirmation_index == 2
    assert detect_fvg(candles[:2]) == []
