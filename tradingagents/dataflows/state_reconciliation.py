from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tradingagents.dataflows.intraday_types import Candle, MarketTick, Timeframe


@dataclass
class ReconciliationResult:
    """Structured outcome for a trading-state comparison."""

    status: str
    proceed: bool
    alert_event: dict[str, Any] | None = None
    reconciliation_event: dict[str, Any] = field(default_factory=dict)


class MockBrokerExecutionAdapter:
    """Minimal broker-state adapter used before a real broker implementation exists."""

    def __init__(self, *, snapshot: Mapping[str, Any] | None = None):
        self.snapshot = dict(snapshot or {})

    def get_account_snapshot(self) -> dict[str, Any]:
        return dict(self.snapshot)


def _normalize_positions(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    positions = dict(raw)
    for key, value in list(positions.items()):
        if isinstance(value, dict):
            positions[key] = dict(value)
        else:
            positions[key] = value
    return positions


def reconcile_state_against_broker(
    internal_state: Mapping[str, Any] | None,
    broker_adapter: MockBrokerExecutionAdapter,
) -> ReconciliationResult:
    """Compare internal position/order state against the broker's reported state.

    Outcome (a): matching state -> resume.
    Outcome (b): mismatch -> halt and emit alert event; no silent correction.
    Outcome (c): always emit a reconciliation event so operators can observe the result.
    """
    internal = dict(internal_state or {})
    broker = dict(broker_adapter.get_account_snapshot())
    internal_positions = _normalize_positions(internal.get("positions"))
    broker_positions = _normalize_positions(broker.get("positions"))
    internal_orders = internal.get("orders") or []
    broker_orders = broker.get("orders") or []

    match = (
        internal_positions == broker_positions
        and internal_orders == broker_orders
    )

    if match:
        event = {
            "event": "reconciliation_result",
            "status": "resume",
            "symbol": "XAUUSD",
            "internal_positions": internal_positions,
            "broker_positions": broker_positions,
            "internal_orders": internal_orders,
            "broker_orders": broker_orders,
        }
        return ReconciliationResult(status="resume", proceed=True, reconciliation_event=event)

    alert = {
        "type": "state_mismatch_alert",
        "event": "reconciliation_result",
        "status": "halt",
        "details": {
            "internal_positions": internal_positions,
            "broker_positions": broker_positions,
            "internal_orders": internal_orders,
            "broker_orders": broker_orders,
        },
    }
    event = {
        "event": "reconciliation_result",
        "status": "halt",
        "symbol": "XAUUSD",
        "internal_positions": internal_positions,
        "broker_positions": broker_positions,
        "internal_orders": internal_orders,
        "broker_orders": broker_orders,
    }
    return ReconciliationResult(status="halt", proceed=False, alert_event=alert, reconciliation_event=event)


def canonicalize_timeframe(value: str | Timeframe | None) -> Timeframe:
    """Normalize a timeframe string into the canonical XAUUSD enum."""
    if value is None:
        return Timeframe.M5
    if isinstance(value, Timeframe):
        return value
    normalized = str(value).strip().lower()
    for timeframe in Timeframe:
        if timeframe.value == normalized:
            return timeframe
    raise ValueError(f"Unsupported timeframe: {value!r}")


def _iso_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _latest_timestamp_for(snapshot: Mapping[str, Any] | None) -> str | None:
    if snapshot is None:
        return None
    for key in ("latest_timestamp", "timestamp", "ts", "time"):
        if key in snapshot and snapshot[key] is not None:
            return _iso_timestamp(snapshot[key])
    return None


def _merge_candle_lists(previous: Sequence[Candle] | None, current: Sequence[Candle] | None) -> list[Candle]:
    merged: dict[str, Candle] = {}
    for candle in (previous or []):
        merged[candle.timestamp] = candle
    for candle in (current or []):
        merged[candle.timestamp] = candle
    return sorted(merged.values(), key=lambda item: item.timestamp)


def reconcile_market_state(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    *,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    """Merge two market snapshots while preserving the newest valid state.

    The newest snapshot wins when its timestamp is newer than the previous state.
    If the newer payload is older or missing, the previous state is retained.
    This keeps state reconciliation deterministic and prevents stale rows from
    overwriting a fresher market state.
    """
    previous_state = dict(previous or {})
    current_state = dict(current or {})
    previous_ts = _latest_timestamp_for(previous_state)
    current_ts = _latest_timestamp_for(current_state)

    if current_ts is None:
        result = previous_state or {"symbol": symbol, "timeframe": Timeframe.M5.value}
        result.setdefault("source", "previous")
        return result

    if previous_ts is not None and current_ts < previous_ts:
        previous_state.setdefault("source", "previous")
        return previous_state

    merged = {**previous_state, **current_state}
    merged.setdefault("symbol", symbol)
    if "timeframe" not in merged:
        merged["timeframe"] = Timeframe.M5.value

    if "candles" in merged or "bars" in merged:
        candles = merged.get("candles", merged.get("bars", []))
        try:
            merged["candles"] = _merge_candle_lists(
                previous_state.get("candles"),
                current_state.get("candles"),
            )
        except Exception:
            pass

    if "latest_close" in current_state and "latest_close" not in merged:
        merged["latest_close"] = current_state["latest_close"]

    merged["latest_timestamp"] = current_ts
    merged["source"] = "incoming" if current_ts >= (previous_ts or current_ts) else "previous"
    return merged


__all__ = [
    "MockBrokerExecutionAdapter",
    "ReconciliationResult",
    "canonicalize_timeframe",
    "reconcile_market_state",
    "reconcile_state_against_broker",
]
