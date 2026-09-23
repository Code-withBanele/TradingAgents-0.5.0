from __future__ import annotations

import pytest

from tradingagents.dataflows.state_reconciliation import (
    MockBrokerExecutionAdapter,
    reconcile_state_against_broker,
)


@pytest.mark.unit
def test_state_reconciliation_resumes_when_broker_matches_internal_snapshot():
    internal_state = {
        "positions": {"XAUUSD": {"qty": 2.0, "avg_price": 2340.0}},
        "orders": [],
    }
    broker = MockBrokerExecutionAdapter(snapshot={
        "positions": {"XAUUSD": {"qty": 2.0, "avg_price": 2340.0}},
        "orders": [],
    })

    result = reconcile_state_against_broker(internal_state, broker)

    assert result.status == "resume"
    assert result.proceed is True
    assert result.alert_event is None
    assert result.reconciliation_event["status"] == "resume"


@pytest.mark.unit
def test_state_reconciliation_halts_and_alerts_on_mismatch():
    internal_state = {
        "positions": {"XAUUSD": {"qty": 2.0, "avg_price": 2340.0}},
        "orders": [],
    }
    broker = MockBrokerExecutionAdapter(snapshot={
        "positions": {"XAUUSD": {"qty": 1.0, "avg_price": 2340.0}},
        "orders": [],
    })

    result = reconcile_state_against_broker(internal_state, broker)

    assert result.status == "halt"
    assert result.proceed is False
    assert result.alert_event is not None
    assert result.alert_event["type"] == "state_mismatch_alert"
    assert result.reconciliation_event["status"] == "halt"
