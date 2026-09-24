from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.dataflows.intraday_types import Candle
from tradingagents.dataflows.market_structure import (
    CISDDefinition,
    DealingRangeSource,
    InstrumentConfig,
    StructureDirection,
    calculate_premium_discount,
    detect_cisd,
    detect_fvg,
    detect_ifvg,
    detect_previous_levels,
    detect_session_context,
)


def candles(rows):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [Candle(symbol="XAUUSD", timestamp=(start + timedelta(minutes=i * 5)).isoformat(),
                   open=o, high=h, low=low, close=c, volume=1)
            for i, (o, h, low, c) in enumerate(rows)]


@pytest.mark.parametrize("rows,direction", [
    ([(10, 10.2, 8.8, 9), (9, 11.2, 8.9, 11), (11, 11.7, 10.8, 11.5)], StructureDirection.BULLISH),
    ([(9, 11.2, 8.8, 11), (11, 11.1, 8.7, 8.9), (8.9, 9.2, 8.3, 8.5)], StructureDirection.BEARISH),
])
def test_cisd_v1_directional_acceptance(rows, direction):
    event = detect_cisd(candles(rows), definition=CISDDefinition())[0]
    assert event.direction == direction
    assert event.status == "CONFIRMED"
    assert event.definition_version == "cisd-v1"


def test_cisd_wick_only_cross_is_not_candidate():
    assert detect_cisd(candles([(10, 10.2, 8.8, 9), (9, 10.8, 8.9, 9.5)])) == []


def test_cisd_invalidated_and_incomplete_candidates_are_reported():
    invalid = detect_cisd(candles([(10, 10.2, 8.8, 9), (9, 11.2, 8.9, 11), (10, 10.2, 8.5, 8.7)]))[0]
    incomplete = detect_cisd(candles([(10, 10.2, 8.8, 9), (9, 11.2, 8.9, 11)]))[0]
    assert invalid.status == "INVALIDATED"
    assert incomplete.status == "INCOMPLETE"


def test_instrument_config_is_explicit_and_validated():
    gold = InstrumentConfig(symbol="XAUUSD", pip_size=0.01, price_decimals=2, tick_size=0.01)
    assert gold.price_decimals == 2
    with pytest.raises(ValueError):
        InstrumentConfig(pip_size=0)


def test_previous_levels_use_previous_available_local_day_and_week():
    data = []
    # Friday, Monday (current); prior week must not alias prior day.
    for stamp, high, low in [
        ("2024-01-05T12:00:00Z", 15, 5),
        ("2024-01-08T09:00:00Z", 30, 20),
        ("2024-01-08T12:00:00Z", 32, 18),
    ]:
        data.append(Candle(symbol="XAUUSD", timestamp=stamp, open=high, high=high, low=low,
                           close=low, volume=1))
    levels = detect_previous_levels(data)
    assert (levels["PDH"], levels["PDL"]) == (15, 5)
    assert (levels["PWH"], levels["PWL"]) == (15, 5)


def test_session_ranges_only_include_candles_in_current_session_window():
    data = [
        Candle(symbol="XAUUSD", timestamp="2024-03-11T07:00:00Z", open=1, high=99, low=0, close=1, volume=1),
        Candle(symbol="XAUUSD", timestamp="2024-03-11T09:00:00Z", open=1, high=4, low=2, close=3, volume=1),
        Candle(symbol="XAUUSD", timestamp="2024-03-11T12:30:00Z", open=1, high=5, low=1, close=3, volume=1),
    ]
    context = detect_session_context(data)
    assert context.session_high == 5
    assert context.session_low == 1
    assert context.session_start is not None and context.session_end is not None


def test_premium_discount_requires_declared_range_source():
    with pytest.raises(ValueError):
        calculate_premium_discount(candles([(1, 2, 0, 1)]), source=DealingRangeSource.CUSTOM_RANGE)
    state = calculate_premium_discount(candles([(1, 2, 0, 1)]), source=DealingRangeSource.CUSTOM_RANGE,
                                       custom_range=(90, 110))
    assert state.range_high == 110
    assert state.range_low == 90


def test_fvg_lifecycle_partial_full_and_invalid_states():
    base = [(9, 10, 8, 9), (10, 10.5, 9, 10), (11, 12, 11, 11.5)]
    created = detect_fvg(candles(base))[0]
    partial = detect_fvg(candles(base + [(11, 11.2, 10.5, 10.8)]))[0]
    full = detect_fvg(candles(base + [(11, 11.2, 9.9, 10.2)]))[0]
    invalid = detect_fvg(candles(base + [(11, 11.2, 9.8, 9.9)]))[0]
    assert created.status == "CREATED"
    assert partial.status == "PARTIALLY_MITIGATED"
    assert full.status == "FULLY_MITIGATED"
    assert invalid.status == "INVALIDATED"


def test_ifvg_requires_original_gap_failure_then_opposite_acceptance():
    history = candles([(9, 10, 8, 9), (10, 10.5, 9, 10), (11, 12, 11, 11.5),
                       (10.5, 10.8, 9.8, 9.9), (9.9, 10, 9.5, 9.7)])
    inverse = detect_ifvg(history)
    assert len(inverse) == 1
    assert inverse[0].original_direction == StructureDirection.BULLISH
    assert inverse[0].new_direction == StructureDirection.BEARISH
