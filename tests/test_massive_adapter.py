from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import requests

from tradingagents.dataflows.intraday_types import Candle, Timeframe
from tradingagents.dataflows.market_data_provider import (
    MassiveDataProvider,
    MassiveHistoricalAdapter,
    MassiveProviderError,
    MockDataProvider,
)
from tradingagents.dataflows.market_structure import evaluate_strategy, to_quant_signal
from tradingagents.dataflows.xauusd_data_layer import XAUUSDDataLayer
from tradingagents.quant.models import StructureDirection, TradeSetup


class _Response:
    def __init__(self, payload=None, status_code=200, headers=None, error=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.error = error

    def json(self):
        if self.error:
            raise self.error
        return self.payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _range():
    start = datetime(2025, 1, 2, tzinfo=timezone.utc)
    return start, start + timedelta(minutes=10)


def _bar(ts, o=2650.0, h=2652.0, low=2649.0, c=2651.0, volume=12):
    return {"t": ts, "o": o, "h": h, "l": low, "c": c, "v": volume, "vw": c, "n": 7}


def _payload(results=None, **extra):
    return {"status": "OK", "ticker": "C:XAUUSD", "request_id": "request-1", "results": results or [], **extra}


def test_massive_maps_canonical_symbol_and_normalizes_candles_with_metadata_and_cache(tmp_path):
    start, end = _range()
    timestamp = int(start.timestamp() * 1000)
    session = _Session([_Response(_payload([_bar(timestamp)]))])
    adapter = MassiveHistoricalAdapter("test-secret", session=session, cache_dir=tmp_path)
    provider = MassiveDataProvider(adapter=adapter)

    first = asyncio.run(provider.get_historical_candles("XAUUSD", Timeframe.M1, start, end))
    second = asyncio.run(provider.get_historical_candles("XAUUSD", Timeframe.M1, start, end))

    assert first == second
    assert isinstance(first[0], Candle)
    assert first[0].symbol == "XAUUSD"
    assert first[0].timeframe == Timeframe.M1
    assert first[0].timestamp == start.isoformat()
    assert first[0].volume == 12
    assert session.calls[0][0].startswith("https://api.massive.com/v2/aggs/ticker/C:XAUUSD/range/1/minute/")
    assert session.calls[0][1] == {"Authorization": "Bearer test-secret"}
    assert "test-secret" not in session.calls[0][0]
    metadata = provider.get_dataset_metadata(timeframe=Timeframe.M1)
    assert metadata["provider_symbol"] == "C:XAUUSD"
    assert metadata["cache_hit"] is True
    assert metadata["raw_data"][0]["provider_metadata"]["n"] == 7
    assert len(session.calls) == 1


def test_massive_requires_key_and_accepts_only_spot_gold_symbols(tmp_path):
    start, end = _range()
    with pytest.raises(MassiveProviderError, match="MASSIVE_API_KEY") as missing:
        MassiveHistoricalAdapter("", cache_dir=tmp_path).fetch("XAUUSD", Timeframe.M5, start, end)
    assert missing.value.code == "CONFIGURATION_ERROR"

    adapter = MassiveHistoricalAdapter("key", session=_Session([]), cache_dir=tmp_path)
    assert adapter.map_symbol("XAUUSD") == "C:XAUUSD"
    assert adapter.map_symbol("C:XAUUSD") == "C:XAUUSD"
    for wrong in ("GC", "GC1!", "XAUUSD=X", "XAU/USD"):
        with pytest.raises(MassiveProviderError) as err:
            adapter.map_symbol(wrong)
        assert err.value.code == "SYMBOL_UNAVAILABLE"


def test_massive_loads_key_from_environment_without_exposing_it(monkeypatch, tmp_path):
    monkeypatch.setenv("MASSIVE_API_KEY", "loaded-secret")
    adapter = MassiveHistoricalAdapter(cache_dir=tmp_path)
    assert adapter.api_key == "loaded-secret"
    assert "loaded-secret" not in repr(adapter)


def test_massive_empty_response_and_missing_intervals_are_reported(tmp_path):
    start, end = _range()
    adapter = MassiveHistoricalAdapter("key", session=_Session([_Response(_payload())]), cache_dir=tmp_path)
    provider = MassiveDataProvider(adapter=adapter)
    assert asyncio.run(provider.get_historical_candles("XAUUSD", Timeframe.M1, start, end)) == []
    assert provider.get_dataset_metadata(timeframe=Timeframe.M1)["data_quality"]["row_count"] == 0

    bars = [_bar(int(start.timestamp() * 1000)), _bar(int((start + timedelta(minutes=3)).timestamp() * 1000))]
    session = _Session([_Response(_payload(bars))])
    provider = MassiveDataProvider(adapter=MassiveHistoricalAdapter("key", session=session, cache_dir=tmp_path / "gaps"))
    asyncio.run(provider.get_historical_candles("XAUUSD", Timeframe.M1, start, end))
    assert provider.get_dataset_metadata(timeframe=Timeframe.M1)["data_quality"]["missing_interval_count"] == 2


@pytest.mark.parametrize("bars", [
    [_bar(1735776000000, h=2640)],
    [_bar(1735776000000), _bar(1735776000000)],
])
def test_massive_fails_closed_on_invalid_ohlc_or_duplicate_timestamps(tmp_path, bars):
    start, end = _range()
    provider = MassiveDataProvider(adapter=MassiveHistoricalAdapter(
        "key", session=_Session([_Response(_payload(bars))]), cache_dir=tmp_path,
    ))
    with pytest.raises(MassiveProviderError) as error:
        asyncio.run(provider.get_historical_candles("XAUUSD", Timeframe.M1, start, end))
    assert error.value.code == "DATA_QUALITY_ERROR"


@pytest.mark.parametrize(("response", "code"), [
    (_Response({}, status_code=401), "AUTHENTICATION_FAILED"),
    (_Response({}, status_code=403), "AUTHENTICATION_FAILED"),
    (_Response({}, status_code=404), "SYMBOL_UNAVAILABLE"),
    (_Response({}, status_code=500), "PROVIDER_UNAVAILABLE"),
    (_Response(error=ValueError("bad json")), "PROVIDER_UNAVAILABLE"),
    (requests.Timeout(), "PROVIDER_UNAVAILABLE"),
    (requests.ConnectionError(), "PROVIDER_UNAVAILABLE"),
])
def test_massive_provider_failures_are_sanitized_and_classified(tmp_path, response, code):
    start, end = _range()
    adapter = MassiveHistoricalAdapter(
        "secret-must-not-leak", session=_Session([response]), cache_dir=tmp_path,
        max_retries=0, backoff_seconds=0,
    )
    with pytest.raises(MassiveProviderError) as error:
        adapter.fetch("XAUUSD", Timeframe.M5, start, end)
    assert error.value.code == code
    assert "secret-must-not-leak" not in str(error.value)


def test_massive_rate_limit_retries_are_bounded(tmp_path):
    start, end = _range()
    waits = []
    session = _Session([
        _Response({}, status_code=429, headers={"Retry-After": "2"}),
        _Response({}, status_code=429, headers={"Retry-After": "2"}),
        _Response({}, status_code=429, headers={"Retry-After": "2"}),
    ])
    adapter = MassiveHistoricalAdapter("key", session=session, cache_dir=tmp_path,
                                       max_retries=2, sleep=waits.append)
    with pytest.raises(MassiveProviderError) as error:
        adapter.fetch("XAUUSD", Timeframe.M1, *_range())
    assert error.value.code == "RATE_LIMITED"
    assert len(session.calls) == 3
    assert waits == [2.0, 2.0]


def test_massive_capabilities_and_connection_test(tmp_path):
    start, end = _range()
    timestamp = int(start.timestamp() * 1000)
    provider = MassiveDataProvider(adapter=MassiveHistoricalAdapter(
        "key", session=_Session([_Response(_payload([_bar(timestamp)]))]), cache_dir=tmp_path,
    ))
    assert provider.capabilities() == {"historical_candles", "volume"}
    assert provider.capability_details()["market_depth"] == "unsupported_for_this_adapter"
    assert asyncio.run(provider.test_connection(start=start, end=end, timeframe=Timeframe.M1))["status"] == "CONNECTED"


def test_massive_data_layer_and_quant_setup_preserve_timeframe_and_strategy_identity(tmp_path):
    start, end = _range()
    timestamp = int(start.timestamp() * 1000)
    provider = MassiveDataProvider(adapter=MassiveHistoricalAdapter(
        "key", session=_Session([_Response(_payload([_bar(timestamp)]))]), cache_dir=tmp_path,
    ))
    layer = XAUUSDDataLayer(provider=provider)
    candles = asyncio.run(layer.get_historical_candles(start, end, timeframe=Timeframe.M1))
    setup = evaluate_strategy(candles, strategy_id="LIQUIDITY_SWEEP_FVG_REVERSAL")
    assert setup.timeframe == "1m"
    assert setup.strategy_id == "LIQUIDITY_SWEEP_FVG_REVERSAL"

    valid_setup = TradeSetup(
        strategy_id="LIQUIDITY_SWEEP_FVG_REVERSAL",
        strategy_version="v0.1",
        direction=StructureDirection.BULLISH,
        status="VALID",
        entry=2650.0,
        stop=2648.0,
        target=2655.0,
        timestamp=start.isoformat(),
        timeframe="1m",
    )
    signal = to_quant_signal(valid_setup, symbol="XAUUSD")
    assert signal is not None
    assert signal.timeframe == "1m"
    assert signal.strategy_id == valid_setup.strategy_id
    assert signal.strategy_version == "v0.1"


def test_xauusd_data_layer_uses_configured_massive_provider_and_accepts_mock_override():
    assert isinstance(XAUUSDDataLayer().provider, MassiveDataProvider)
    assert isinstance(XAUUSDDataLayer(provider=MockDataProvider()).provider, MockDataProvider)


def test_massive_pagination_rejects_untrusted_next_url(tmp_path):
    start, end = _range()
    first = _payload([_bar(int(start.timestamp() * 1000))], next_url="https://attacker.invalid/steal")
    adapter = MassiveHistoricalAdapter("key", session=_Session([_Response(first)]), cache_dir=tmp_path)
    with pytest.raises(MassiveProviderError, match="untrusted"):
        adapter.fetch("XAUUSD", Timeframe.M1, start, end)


def test_massive_rejects_response_for_a_different_ticker(tmp_path):
    start, end = _range()
    adapter = MassiveHistoricalAdapter(
        "key",
        session=_Session([_Response(_payload([_bar(int(start.timestamp() * 1000))], ticker="C:EURUSD"))]),
        cache_dir=tmp_path,
    )
    with pytest.raises(MassiveProviderError) as error:
        adapter.fetch("XAUUSD", Timeframe.M1, start, end)
    assert error.value.code == "SYMBOL_UNAVAILABLE"
