from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.dataflows.intraday_types import Timeframe
from tradingagents.dataflows.market_data_provider import FreeHistoricalDataProvider


@pytest.mark.unit
def test_dataset_metadata_populated_and_stored_in_utc():
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
            "volume": "N/A",
        },
    ]

    provider = FreeHistoricalDataProvider(provider="demo")
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=5)
    provider.ingest_rows("XAUUSD", Timeframe.M5, rows, start=start, end=end)

    metadata = provider.get_dataset_metadata("XAUUSD", Timeframe.M5)
    assert metadata["provider"] == "demo"
    assert metadata["symbol"] == "XAUUSD"
    assert metadata["timeframe"] == Timeframe.M5
    assert metadata["timezone"] == "UTC"
    assert metadata["start_date"].endswith("+00:00")
    assert metadata["end_date"].endswith("+00:00")
    assert metadata["retrieval_timestamp"].endswith("+00:00")
    assert "CFD volume" in metadata["volume_type_note"]
    assert metadata["raw_data"]
    assert metadata["normalized_data"]
    assert metadata["normalized_data"][1]["volume"] == 0.0
