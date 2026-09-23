from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.dataflows.intraday_types import Candle, Timeframe
from tradingagents.dataflows.market_data_provider import (
    BrokerDataProvider,
    FreeHistoricalDataProvider,
    MockDataProvider,
    TradingViewDataProvider,
)


@pytest.mark.unit
def test_provider_capabilities_report_expected_support():
    assert MockDataProvider().capabilities() == {
        "historical_candles",
        "realtime_candles",
        "volume",
    }
    assert FreeHistoricalDataProvider().capabilities() == {
        "historical_candles",
        "volume",
    }
    assert BrokerDataProvider().capabilities() == set()
    assert TradingViewDataProvider().capabilities() == set()


@pytest.mark.unit
def test_mock_provider_is_deterministic_across_runs():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)

    first = asyncio.run(MockDataProvider().get_historical_candles("XAUUSD", Timeframe.M5, start, end))
    second = asyncio.run(MockDataProvider().get_historical_candles("XAUUSD", Timeframe.M5, start, end))

    assert first == second
    assert all(isinstance(candle, Candle) for candle in first)
    assert first[0].symbol == "XAUUSD"
    assert first[0].timeframe == Timeframe.M5


@pytest.mark.unit
def test_free_historical_provider_normalizes_rows_into_canonical_candles():
    rows = [
        {
            "timestamp": "2026-09-01T00:00:00+02:00",
            "open": "2334.25",
            "high": "2336.00",
            "low": "2333.75",
            "close": "2335.20",
            "volume": "1200",
        },
        {
            "timestamp": "2026-09-01T00:05:00+02:00",
            "open": "2335.20",
            "high": "2336.80",
            "low": "2334.60",
            "close": "2335.90",
            "volume": None,
        },
    ]

    provider = FreeHistoricalDataProvider(provider="demo")
    candles = provider.normalize_rows("XAUUSD", Timeframe.M5, rows)

    assert len(candles) == 2
    assert candles[0].timestamp == "2026-08-31T22:00:00+00:00"
    assert candles[1].volume == 0.0
    assert candles[0].timeframe == Timeframe.M5
    assert all(isinstance(candle, Candle) for candle in candles)
