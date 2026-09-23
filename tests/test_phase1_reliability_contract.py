from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from tradingagents.dataflows.intraday_types import Candle, MarketTick, Timeframe
from tradingagents.llm_clients.reliability import call_with_llm_reliability
from tradingagents.xauusd_config import XAUUSD_CONFIG


class DecisionResult(BaseModel):
    decision: str = Field(pattern="^(BUY|SELL|HOLD|NO_TRADE)$")
    confidence: float = Field(ge=0.0, le=1.0)


@pytest.mark.unit
def test_reliability_cache_is_persistent_across_calls(tmp_path):
    cache_path = tmp_path / "llm_cache.sqlite"
    calls = {"count": 0}

    def invoke(prompt):
        calls["count"] += 1
        return {"decision": "BUY", "confidence": 0.82}

    first = call_with_llm_reliability(
        model="gpt-4.1-mini",
        strategy_version="v0.1",
        prompt_inputs={"ticker": "XAUUSD", "window": "2026-09-01"},
        invoke_fn=invoke,
        schema=DecisionResult,
        cache_path=cache_path,
        max_retries=1,
    )
    second = call_with_llm_reliability(
        model="gpt-4.1-mini",
        strategy_version="v0.1",
        prompt_inputs={"ticker": "XAUUSD", "window": "2026-09-01"},
        invoke_fn=invoke,
        schema=DecisionResult,
        cache_path=cache_path,
        max_retries=1,
    )

    assert first == second
    assert calls["count"] == 1


@pytest.mark.unit
def test_fail_closed_when_all_retries_are_exhausted(tmp_path):
    def invoke(prompt):
        raise TimeoutError("provider timed out")

    result = call_with_llm_reliability(
        model="gpt-4.1-mini",
        strategy_version="v0.1",
        prompt_inputs={"ticker": "XAUUSD", "window": "2026-09-01"},
        invoke_fn=invoke,
        schema=DecisionResult,
        cache_path=tmp_path / "cache.sqlite",
        max_retries=2,
        retry_backoff_seconds=0.0,
    )

    assert result is None


@pytest.mark.unit
def test_schema_validation_retries_until_valid_response(tmp_path):
    values = iter([
        {"decision": "INVALID", "confidence": 1.3},
        {"decision": "BUY", "confidence": 0.75},
    ])

    def invoke(prompt):
        return next(values)

    result = call_with_llm_reliability(
        model="gpt-4.1-mini",
        strategy_version="v0.1",
        prompt_inputs={"ticker": "XAUUSD", "window": "2026-09-01"},
        invoke_fn=invoke,
        schema=DecisionResult,
        cache_path=tmp_path / "cache.sqlite",
        max_retries=3,
        retry_backoff_seconds=0.0,
    )

    assert result == {"decision": "BUY", "confidence": 0.75}


@pytest.mark.unit
def test_intraday_types_define_canonical_xauusd_timeframes():
    assert Timeframe.M1.value == "1m"
    assert Timeframe.M5.value == "5m"

    candle = Candle(
        symbol="XAUUSD",
        timestamp="2026-09-01T12:00:00Z",
        open=2340.12,
        high=2344.10,
        low=2338.44,
        close=2342.70,
        volume=1124,
        timeframe=Timeframe.M5,
    )
    tick = MarketTick(
        symbol="XAUUSD",
        timestamp="2026-09-01T12:00:00Z",
        bid=2342.63,
        ask=2342.89,
        last=2342.72,
        volume=27,
        spread=0.26,
    )

    assert candle.symbol == "XAUUSD"
    assert tick.spread == 0.26


@pytest.mark.unit
def test_xauusd_config_defaults_are_paper_and_non_live():
    assert XAUUSD_CONFIG["trading_mode"] == "paper"
    assert XAUUSD_CONFIG["live_trading"] is False
    assert XAUUSD_CONFIG["symbol"] == "XAUUSD"
    assert Timeframe.M1 in {Timeframe.M1, Timeframe.M5}
