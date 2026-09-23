from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows.intraday_types import Candle, Timeframe
from tradingagents.dataflows.state_reconciliation import canonicalize_timeframe, reconcile_market_state
from tradingagents.dataflows.xauusd_data_layer import XAUUSDDataLayer


@pytest.mark.unit
def test_timeframe_normalization_accepts_enum_and_string():
    assert canonicalize_timeframe("5m") == Timeframe.M5
    assert canonicalize_timeframe(Timeframe.M1) == Timeframe.M1


@pytest.mark.unit
def test_reconcile_market_state_keeps_newest_snapshot():
    previous = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "latest_timestamp": "2026-09-01T11:55:00Z",
        "latest_close": 2335.10,
    }
    current = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "latest_timestamp": "2026-09-01T12:00:00Z",
        "latest_close": 2336.20,
    }

    reconciled = reconcile_market_state(previous, current)
    assert reconciled["latest_close"] == 2336.20
    assert reconciled["source"] == "incoming"


@pytest.mark.unit
def test_reconcile_market_state_rejects_older_snapshot():
    previous = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "latest_timestamp": "2026-09-01T12:00:00Z",
        "latest_close": 2336.20,
    }
    current = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "latest_timestamp": "2026-09-01T11:55:00Z",
        "latest_close": 2335.10,
    }

    reconciled = reconcile_market_state(previous, current)
    assert reconciled["latest_close"] == 2336.20
    assert reconciled["source"] == "previous"


@pytest.mark.unit
def test_xauusd_data_layer_emits_canonical_candle_models(monkeypatch):
    df = pd.DataFrame(
        {
            "Date": ["2026-09-01", "2026-09-02"],
            "Open": [2334.0, 2335.5],
            "High": [2335.0, 2337.0],
            "Low": [2333.0, 2334.0],
            "Close": [2334.5, 2336.2],
            "Volume": [1000, 1100],
        }
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.xauusd_data_layer.load_ohlcv",
        lambda *a, **k: df,
    )

    data = XAUUSDDataLayer()
    candles = data.load_candles("2026-09-02")

    assert len(candles) == 2
    assert isinstance(candles[0], Candle)
    assert candles[-1].symbol == "XAUUSD"
    assert candles[-1].timeframe == Timeframe.M5
    assert candles[-1].close == 2336.2


@pytest.mark.unit
def test_snapshot_state_has_latest_bar_and_timestamp(monkeypatch):
    df = pd.DataFrame(
        {
            "Date": ["2026-09-01", "2026-09-02"],
            "Open": [2334.0, 2335.5],
            "High": [2335.0, 2337.0],
            "Low": [2333.0, 2334.0],
            "Close": [2334.5, 2336.2],
            "Volume": [1000, 1100],
        }
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.xauusd_data_layer.load_ohlcv",
        lambda *a, **k: df,
    )

    state = XAUUSDDataLayer().snapshot_state("2026-09-02")
    assert state["symbol"] == "XAUUSD"
    assert state["latest_close"] == 2336.2
    assert state["latest_timestamp"].startswith("2026-09-02")
