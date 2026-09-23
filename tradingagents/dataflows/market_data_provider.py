from __future__ import annotations

import csv
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from tradingagents.dataflows.intraday_types import Candle, MarketTick, Timeframe


@dataclass
class MarketEvent:
    """Generic market update emitted from a provider subscription."""

    symbol: str
    timestamp: datetime | str
    kind: str = "candle"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Subscription:
    """Minimal subscription handle for provider callbacks."""

    symbol: str
    callback: Callable[[MarketEvent], None]
    closed: bool = False

    def unsubscribe(self) -> None:
        self.closed = True


@runtime_checkable
class MarketDataProvider(Protocol):
    async def get_historical_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]: ...

    async def get_latest_candle(
        self, symbol: str, timeframe: Timeframe
    ) -> Candle: ...

    async def subscribe(
        self, symbol: str, callback: Callable[[MarketEvent], None]
    ) -> Subscription: ...

    def capabilities(self) -> set[str]: ...


@runtime_checkable
class HistoricalDataAdapter(Protocol):
    def fetch(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list[dict[str, Any]]: ...


def _parse_iso_datetime(value: str | datetime | None) -> datetime:
    if value is None:
        raise ValueError("timestamp is required")
    if isinstance(value, datetime):
        dt = value
    else:
        raw = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_utc_iso(value: str | datetime | None) -> str:
    if value is None:
        raise ValueError("timestamp is required")
    dt = _parse_iso_datetime(value)
    return dt.astimezone(timezone.utc).isoformat()


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return float(default)
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"", "na", "n/a", "null", "none", "nan"}:
            return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class CsvHistoricalAdapter:
    """Simple adapter for CSV exports with OHLCV-style columns."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list[dict[str, Any]]:
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows: list[dict[str, Any]] = []
            for row in reader:
                ts_raw = row.get("timestamp") or row.get("Datetime") or row.get("Date")
                if ts_raw is None:
                    continue
                dt = _parse_iso_datetime(ts_raw)
                if dt < start or dt > end:
                    continue
                rows.append(row)
            return rows


class JsonHistoricalAdapter:
    """Simple adapter for JSON array payloads with OHLCV-style rows."""

    def __init__(self, payload: str | list[dict[str, Any]] | Path):
        if isinstance(payload, (str, Path)):
            source = Path(payload)
            loaded = json.loads(source.read_text(encoding="utf-8"))
        else:
            loaded = payload
        if isinstance(loaded, dict):
            self.payload: list[dict[str, Any]] = loaded.get("data", [])
        else:
            self.payload = list(loaded)

    def fetch(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in self.payload:
            ts_raw = row.get("timestamp") or row.get("Datetime") or row.get("Date")
            if ts_raw is None:
                continue
            dt = _parse_iso_datetime(ts_raw)
            if dt < start or dt > end:
                continue
            rows.append(row)
        return rows


class MockDataProvider:
    """Deterministic synthetic XAUUSD candles for tests and early development."""

    _BASE = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    _BASE_CLOSE = 2340.0

    def __init__(self, symbol: str = "XAUUSD"):
        self.symbol = symbol.upper()

    def capabilities(self) -> set[str]:
        return {"historical_candles", "realtime_candles", "volume"}

    async def get_historical_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        if end <= start:
            return []
        step_minutes = 5 if timeframe == Timeframe.M5 else 1
        candles: list[Candle] = []
        cursor = _parse_iso_datetime(start)
        stop = _parse_iso_datetime(end)
        while cursor < stop:
            index = int((cursor - self._BASE).total_seconds() // 60)
            close = self._BASE_CLOSE + (index * 0.12)
            open_price = close - 0.10
            high = close + 0.18
            low = close - 0.19
            candles.append(
                Candle(
                    symbol=symbol.upper(),
                    timestamp=cursor.astimezone(timezone.utc).isoformat(),
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=1000 + index,
                    timeframe=timeframe,
                )
            )
            cursor += timedelta(minutes=step_minutes)
        return candles

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Candle:
        ts = self._BASE + timedelta(minutes=125 if timeframe == Timeframe.M5 else 135)
        close = self._BASE_CLOSE + 0.12 * (int((ts - self._BASE).total_seconds() // 60))
        return Candle(
            symbol=symbol.upper(),
            timestamp=ts.astimezone(timezone.utc).isoformat(),
            open=close - 0.10,
            high=close + 0.18,
            low=close - 0.19,
            close=close,
            volume=1200,
            timeframe=timeframe,
        )

    async def subscribe(self, symbol: str, callback: Callable[[MarketEvent], None]) -> Subscription:
        candle = await self.get_latest_candle(symbol, Timeframe.M5)
        callback(MarketEvent(symbol=symbol.upper(), timestamp=candle.timestamp, kind="candle", payload={"candle": candle}))
        return Subscription(symbol=symbol.upper(), callback=callback)


class FreeHistoricalDataProvider:
    """Adapter-based historical importer for free data sources and file dumps."""

    def __init__(
        self,
        *,
        provider: str = "free",
        adapter: HistoricalDataAdapter | None = None,
    ):
        self.provider = provider
        self.adapter = adapter
        self._raw_data: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._normalized_data: dict[tuple[str, str], list[Candle]] = {}
        self._metadata: dict[tuple[str, str], dict[str, Any]] = {}

    def capabilities(self) -> set[str]:
        return {"historical_candles", "volume"}

    def normalize_rows(
        self,
        symbol: str,
        timeframe: Timeframe,
        rows: Sequence[dict[str, Any]],
    ) -> list[Candle]:
        normalized: list[Candle] = []
        for row in rows:
            ts_raw = row.get("timestamp") or row.get("datetime") or row.get("Date") or row.get("time")
            if ts_raw is None:
                continue
            dt = _parse_iso_datetime(ts_raw)
            volume = _as_float(row.get("volume"), 0.0)
            candle = Candle(
                symbol=symbol.upper(),
                timestamp=dt.astimezone(timezone.utc).isoformat(),
                open=_as_float(row.get("open"), 0.0),
                high=_as_float(row.get("high"), 0.0),
                low=_as_float(row.get("low"), 0.0),
                close=_as_float(row.get("close"), 0.0),
                volume=volume,
                timeframe=timeframe,
            )
            normalized.append(candle)
        return sorted(normalized, key=lambda item: item.timestamp)

    def ingest_rows(
        self,
        symbol: str,
        timeframe: Timeframe,
        rows: Sequence[dict[str, Any]],
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        timezone_name: str = "UTC",
        provider: str | None = None,
        known_limitations: Iterable[str] | None = None,
    ) -> list[Candle]:
        raw_rows = [dict(row) for row in rows]
        normalized = self.normalize_rows(symbol, timeframe, raw_rows)
        key = (symbol.upper(), timeframe.value)
        self._raw_data[key] = raw_rows
        self._normalized_data[key] = normalized
        start_utc = _parse_iso_datetime(start) if start is not None else _parse_iso_datetime(raw_rows[0]["timestamp"]) if raw_rows else datetime.now(timezone.utc)
        end_utc = _parse_iso_datetime(end) if end is not None else _parse_iso_datetime(raw_rows[-1]["timestamp"]) if raw_rows else datetime.now(timezone.utc)
        metadata: dict[str, Any] = {
            "provider": provider or self.provider,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "start_date": start_utc.astimezone(timezone.utc).isoformat(),
            "end_date": end_utc.astimezone(timezone.utc).isoformat(),
            "timezone": timezone_name.upper() if timezone_name else "UTC",
            "retrieval_timestamp": datetime.now(timezone.utc).isoformat(),
            "volume_type": "source_volume",
            "volume_type_note": (
                "CFD volume and futures volume are not equivalent; this dataset keeps the "
                "source-reported volume field and does not assume futures semantics."
            ),
            "known_limitations": list(known_limitations or ["Source-specific volume semantics may vary by exchange or CFD provider."]),
            "raw_data": raw_rows,
            "normalized_data": [c.model_dump(mode="json") for c in normalized],
        }
        self._metadata[key] = metadata
        return normalized

    async def get_historical_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        if self.adapter is not None:
            rows = self.adapter.fetch(symbol, timeframe, start, end)
            self.ingest_rows(symbol, timeframe, rows, start=start, end=end, provider=self.provider)
            return self._normalized_data[(symbol.upper(), timeframe.value)]
        key = (symbol.upper(), timeframe.value)
        if key not in self._normalized_data:
            raise ValueError(f"No historical dataset for {symbol} / {timeframe.value}.")
        return self._normalized_data[key]

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Candle:
        key = (symbol.upper(), timeframe.value)
        if key not in self._normalized_data:
            raise ValueError(f"No candle data loaded for {symbol} / {timeframe.value}.")
        candles = self._normalized_data[key]
        if not candles:
            raise ValueError(f"No candles available for {symbol} / {timeframe.value}.")
        return candles[-1]

    async def subscribe(self, symbol: str, callback: Callable[[MarketEvent], None]) -> Subscription:
        candle = await self.get_latest_candle(symbol, Timeframe.M5)
        callback(MarketEvent(symbol=symbol.upper(), timestamp=candle.timestamp, kind="candle", payload={"candle": candle}))
        return Subscription(symbol=symbol.upper(), callback=callback)

    def get_dataset_metadata(self, symbol: str, timeframe: Timeframe) -> dict[str, Any]:
        key = (symbol.upper(), timeframe.value)
        metadata = dict(self._metadata.get(key, {}))
        if not metadata:
            return {
                "provider": self.provider,
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "start_date": None,
                "end_date": None,
                "timezone": "UTC",
                "retrieval_timestamp": datetime.now(timezone.utc).isoformat(),
                "volume_type": "source_volume",
                "volume_type_note": "CFD volume and futures volume are not equivalent; this dataset keeps the source-reported volume field and does not assume futures semantics.",
                "known_limitations": ["No source-specific validation yet."],
                "raw_data": [],
                "normalized_data": [],
            }
        metadata["timezone"] = str(metadata.get("timezone", "UTC")).upper()
        metadata["retrieval_timestamp"] = _format_utc_iso(metadata.get("retrieval_timestamp", datetime.now(timezone.utc)))
        if metadata.get("start_date") is not None:
            metadata["start_date"] = _format_utc_iso(metadata["start_date"])
        if metadata.get("end_date") is not None:
            metadata["end_date"] = _format_utc_iso(metadata["end_date"])
        return metadata


class BrokerDataProvider:
    """Stub broker-backed provider. Real credentials are intentionally absent."""

    def capabilities(self) -> set[str]:
        return set()

    async def get_historical_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        raise NotImplementedError("BrokerDataProvider is a stub; broker data integration is not implemented yet.")

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Candle:
        raise NotImplementedError("BrokerDataProvider is a stub; broker data integration is not implemented yet.")

    async def subscribe(self, symbol: str, callback: Callable[[MarketEvent], None]) -> Subscription:
        raise NotImplementedError("BrokerDataProvider is a stub; broker data integration is not implemented yet.")


class TradingViewDataProvider:
    """Stub TradingView-backed provider. Integration is intentionally deferred."""

    def capabilities(self) -> set[str]:
        return set()

    async def get_historical_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        raise NotImplementedError("TradingViewDataProvider is a stub; TradingView integration is not implemented yet.")

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Candle:
        raise NotImplementedError("TradingViewDataProvider is a stub; TradingView integration is not implemented yet.")

    async def subscribe(self, symbol: str, callback: Callable[[MarketEvent], None]) -> Subscription:
        raise NotImplementedError("TradingViewDataProvider is a stub; TradingView integration is not implemented yet.")


__all__ = [
    "BrokerDataProvider",
    "CsvHistoricalAdapter",
    "FreeHistoricalDataProvider",
    "HistoricalDataAdapter",
    "JsonHistoricalAdapter",
    "MarketDataProvider",
    "MarketEvent",
    "MockDataProvider",
    "Subscription",
    "TradingViewDataProvider",
]
