from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import requests

from tradingagents.dataflows.intraday_types import Candle, Timeframe


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


class MassiveProviderError(RuntimeError):
    """Sanitized Massive request/data error; never includes credentials or URLs."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        data_quality: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.data_quality = data_quality


@dataclass(frozen=True)
class DataQualityReport:
    provider: str
    symbol: str
    timeframe: str
    row_count: int
    duplicate_timestamps: int = 0
    invalid_ohlc_rows: int = 0
    missing_interval_count: int = 0
    malformed_rows: int = 0
    request_id: str | None = None


class MassiveHistoricalAdapter:
    """Massive Currencies aggregate adapter for canonical XAUUSD spot candles.

    It deliberately accepts only the public canonical symbol ``XAUUSD`` (or
    the configured Massive symbol), translating it to ``C:XAUUSD`` at the
    provider boundary. API credentials are sent using the Authorization
    header, so request URLs and error messages cannot expose the key.
    """

    _BASE_URL = "https://api.massive.com"
    _PROVIDER_SYMBOL = "C:XAUUSD"
    _CACHE_VERSION = "massive-currencies-aggs-v1"
    _TIMEFRAME = {Timeframe.M1: (1, "minute"), Timeframe.M5: (5, "minute")}

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        cache_dir: str | Path | None = None,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("MASSIVE_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout
        default_cache = Path(os.getenv("TRADINGAGENTS_CACHE_DIR", Path.home() / ".tradingagents" / "cache"))
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache / "massive"
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self._sleep = sleep
        self.last_metadata: dict[str, Any] = {}

    @classmethod
    def map_symbol(cls, symbol: str) -> str:
        canonical = symbol.strip().upper()
        if canonical not in {"XAUUSD", cls._PROVIDER_SYMBOL}:
            raise MassiveProviderError("SYMBOL_UNAVAILABLE", "Massive adapter currently supports XAUUSD spot only.")
        return cls._PROVIDER_SYMBOL

    @classmethod
    def _timeframe(cls, timeframe: Timeframe) -> tuple[int, str, int]:
        try:
            frame = Timeframe(timeframe)
        except (ValueError, TypeError):
            raise MassiveProviderError("CAPABILITY_UNAVAILABLE", f"Massive adapter supports 1m and 5m candles, not {timeframe}.") from None
        if frame not in cls._TIMEFRAME:
            raise MassiveProviderError("CAPABILITY_UNAVAILABLE", f"Massive adapter supports 1m and 5m candles, not {frame.value}.")
        multiplier, span = cls._TIMEFRAME[frame]
        return multiplier, span, 1 if frame == Timeframe.M1 else 5

    @staticmethod
    def _to_ms(value: datetime) -> int:
        return int(_parse_iso_datetime(value).timestamp() * 1000)

    def _cache_path(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> Path:
        key_data = {
            "provider": "massive",
            "provider_symbol": self._PROVIDER_SYMBOL,
            "timeframe": Timeframe(timeframe).value,
            "start": _format_utc_iso(start),
            "end": _format_utc_iso(end),
            "version": self._CACHE_VERSION,
        }
        key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _request_json(self, url: str) -> dict[str, Any]:
        if not self.api_key:
            raise MassiveProviderError("CONFIGURATION_ERROR", "Massive requires MASSIVE_API_KEY.")
        if not url.startswith(self._BASE_URL + "/"):
            raise MassiveProviderError("PROVIDER_UNAVAILABLE", "Massive pagination returned an untrusted endpoint.")
        attempt = 0
        while True:
            try:
                response = self.session.get(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout,
                )
            except requests.Timeout:
                if attempt < self.max_retries:
                    self._sleep(self.backoff_seconds * (2 ** attempt))
                    attempt += 1
                    continue
                raise MassiveProviderError("PROVIDER_UNAVAILABLE", "Massive request timed out after bounded retries.") from None
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    self._sleep(self.backoff_seconds * (2 ** attempt))
                    attempt += 1
                    continue
                raise MassiveProviderError("PROVIDER_UNAVAILABLE", f"Massive request failed after bounded retries ({type(exc).__name__}).") from None

            status = int(response.status_code)
            if status == 429 and attempt < self.max_retries:
                retry_after = (getattr(response, "headers", {}) or {}).get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 12.0
                except (TypeError, ValueError):
                    delay = 12.0
                self._sleep(min(max(0.0, delay), 30.0))
                attempt += 1
                continue
            if status in (401, 403):
                raise MassiveProviderError("AUTHENTICATION_FAILED", "Massive rejected the configured API credentials.", status_code=status)
            if status == 404:
                raise MassiveProviderError("SYMBOL_UNAVAILABLE", "Massive does not provide the requested symbol or endpoint.", status_code=status)
            if status == 429:
                raise MassiveProviderError("RATE_LIMITED", "Massive rate limit remained after bounded retries.", status_code=status)
            if status >= 500:
                raise MassiveProviderError("PROVIDER_UNAVAILABLE", "Massive service returned a server error.", status_code=status)
            if status < 200 or status >= 300:
                raise MassiveProviderError("PROVIDER_UNAVAILABLE", f"Massive request failed with HTTP {status}.", status_code=status)
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError):
                raise MassiveProviderError("PROVIDER_UNAVAILABLE", "Massive returned malformed JSON.", status_code=status) from None
            if not isinstance(payload, dict):
                raise MassiveProviderError("PROVIDER_UNAVAILABLE", "Massive returned an unexpected response shape.", status_code=status)
            return payload

    def fetch(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if not self.api_key:
            raise MassiveProviderError("CONFIGURATION_ERROR", "Massive requires MASSIVE_API_KEY.")
        provider_symbol = self.map_symbol(symbol)
        multiplier, timespan, interval_minutes = self._timeframe(timeframe)
        start_utc, end_utc = _parse_iso_datetime(start), _parse_iso_datetime(end)
        if end_utc <= start_utc:
            self.last_metadata = {"provider_symbol": provider_symbol, "request_id": None, "raw_response_metadata": {}}
            return []

        cache_file = self._cache_path(symbol, timeframe, start_utc, end_utc)
        cache_allowed = end_utc <= datetime.now(timezone.utc) - timedelta(minutes=interval_minutes)
        if cache_allowed and cache_file.is_file():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and isinstance(cached.get("rows"), list):
                    self.last_metadata = dict(cached.get("metadata", {})) | {"cache_hit": True}
                    return cached["rows"]
            except (OSError, ValueError):
                pass

        path = (
            f"/v2/aggs/ticker/{provider_symbol}/range/{multiplier}/{timespan}/"
            f"{self._to_ms(start_utc)}/{self._to_ms(end_utc)}"
        )
        url = self._BASE_URL + path + "?sort=asc&limit=50000"
        rows: list[dict[str, Any]] = []
        request_ids: list[str] = []
        response_metadata: dict[str, Any] = {}
        pages = 0
        while url:
            payload = self._request_json(url)
            pages += 1
            status = str(payload.get("status", "")).upper()
            if status in {"ERROR", "NOT_AUTHORIZED", "DELAYED"}:
                code = "AUTHENTICATION_FAILED" if status == "NOT_AUTHORIZED" else "PROVIDER_UNAVAILABLE"
                raise MassiveProviderError(code, f"Massive aggregate request returned status {status}.")
            response_ticker = payload.get("ticker")
            if response_ticker and str(response_ticker).upper() != provider_symbol:
                raise MassiveProviderError("SYMBOL_UNAVAILABLE", "Massive response ticker did not match C:XAUUSD.")
            results = payload.get("results", [])
            if results is None:
                results = []
            if not isinstance(results, list):
                raise MassiveProviderError("PROVIDER_UNAVAILABLE", "Massive aggregate response results were malformed.")
            response_metadata = {k: payload.get(k) for k in ("ticker", "status", "queryCount", "resultsCount", "request_id", "adjusted") if k in payload}
            if payload.get("request_id"):
                request_ids.append(str(payload["request_id"]))
            for item in results:
                if not isinstance(item, dict):
                    raise MassiveProviderError("DATA_QUALITY_ERROR", "Massive aggregate response contains a malformed row.")
                timestamp = item.get("t")
                try:
                    dt = datetime.fromtimestamp(float(timestamp) / 1000.0, tz=timezone.utc)
                    row = {
                        "timestamp": dt.isoformat(),
                        "open": item["o"], "high": item["h"], "low": item["l"], "close": item["c"],
                        "volume": item.get("v", 0),
                        "provider_metadata": {k: item.get(k) for k in ("vw", "n", "otc") if k in item},
                    }
                except (KeyError, TypeError, ValueError, OverflowError):
                    raise MassiveProviderError("DATA_QUALITY_ERROR", "Massive aggregate response contains missing or invalid OHLC fields.") from None
                rows.append(row)
            next_url = payload.get("next_url")
            if next_url:
                if not isinstance(next_url, str) or not next_url.startswith(self._BASE_URL + "/"):
                    raise MassiveProviderError("PROVIDER_UNAVAILABLE", "Massive returned an untrusted pagination URL.")
                url = next_url
            else:
                url = ""

        rows.sort(key=lambda row: row["timestamp"])
        quality = self._validate_rows(rows, interval_minutes)
        self.last_metadata = {
            "provider_symbol": provider_symbol,
            "request_ids": request_ids,
            "raw_response_metadata": response_metadata,
            "page_count": pages,
            "cache_hit": False,
            "data_quality": quality.__dict__,
        }
        if cache_allowed:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_file.with_suffix(".tmp")
                temporary.write_text(json.dumps({"rows": rows, "metadata": self.last_metadata}), encoding="utf-8")
                temporary.replace(cache_file)
            except OSError:
                # Cache is an optimization; valid data remains usable if local storage is read-only.
                pass
        return rows

    @staticmethod
    def _validate_rows(rows: Sequence[dict[str, Any]], interval_minutes: int) -> DataQualityReport:
        timestamps: set[str] = set()
        duplicate_count = 0
        invalid_ohlc = 0
        previous: datetime | None = None
        gaps = 0
        for row in rows:
            timestamp = row.get("timestamp")
            if not timestamp:
                raise MassiveProviderError("DATA_QUALITY_ERROR", "Massive response contains a row without a timestamp.")
            if timestamp in timestamps:
                duplicate_count += 1
            timestamps.add(timestamp)
            try:
                values = [float(row[name]) for name in ("open", "high", "low", "close")]
                volume = float(row.get("volume", 0) or 0)
                if (
                    not all(math.isfinite(value) and value > 0 for value in values)
                    or values[1] < max(values[0], values[3])
                    or values[2] > min(values[0], values[3])
                    or values[1] < values[2]
                ):
                    invalid_ohlc += 1
                if not math.isfinite(volume) or volume < 0:
                    raise ValueError
            except (TypeError, ValueError):
                invalid_ohlc += 1
            current = _parse_iso_datetime(timestamp)
            if previous is not None:
                gap_minutes = int((current - previous).total_seconds() // 60)
                if gap_minutes > interval_minutes:
                    gaps += max(0, gap_minutes // interval_minutes - 1)
            previous = current
        report = DataQualityReport(
            provider="massive", symbol="XAUUSD", timeframe=f"{interval_minutes}m", row_count=len(rows),
            duplicate_timestamps=duplicate_count, invalid_ohlc_rows=invalid_ohlc,
            missing_interval_count=gaps,
        )
        if duplicate_count:
            raise MassiveProviderError(
                "DATA_QUALITY_ERROR", f"Massive response contains {duplicate_count} duplicate timestamps.",
                data_quality=report.__dict__,
            )
        if invalid_ohlc:
            raise MassiveProviderError(
                "DATA_QUALITY_ERROR", f"Massive response contains {invalid_ohlc} invalid OHLC/volume rows.",
                data_quality=report.__dict__,
            )
        return report


class MassiveDataProvider:
    """Provider-interface implementation for Massive Currencies XAUUSD aggregates."""

    def __init__(self, *, symbol: str = "XAUUSD", adapter: MassiveHistoricalAdapter | None = None, api_key: str | None = None, **adapter_options: Any):
        self.symbol = symbol.upper()
        self.adapter = adapter or MassiveHistoricalAdapter(api_key, **adapter_options)
        self._normalizer = FreeHistoricalDataProvider(provider="massive")
        self._metadata: dict[tuple[str, str], dict[str, Any]] = {}

    def capabilities(self) -> set[str]:
        return {key for key, value in self.capability_details().items() if value == "supported"}

    def capability_details(self) -> dict[str, str]:
        return {
            "historical_candles": "supported",
            "realtime_candles": "subscription_dependent_not_implemented",
            "ticks": "subscription_dependent_not_implemented",
            "bid_ask": "subscription_dependent_not_implemented",
            "spread": "subscription_dependent_not_implemented",
            "volume": "supported",
            "market_depth": "unsupported_for_this_adapter",
            "webhooks": "not_implemented",
        }

    async def get_historical_candles(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list[Candle]:
        rows = await asyncio.to_thread(self.adapter.fetch, symbol, timeframe, start, end)
        candles = self._normalizer.ingest_rows(
            "XAUUSD", Timeframe(timeframe), rows,
            start=start, end=end, provider="massive",
            known_limitations=[
                "Currencies aggregate bars are derived from provider bid/ask quotes, not executed trades.",
                "Missing intervals may reflect forex quote inactivity or market closures.",
                "Access depth and request limits depend on the Massive Currencies subscription.",
            ],
        )
        key = ("XAUUSD", Timeframe(timeframe).value)
        metadata = self._normalizer.get_dataset_metadata("XAUUSD", Timeframe(timeframe))
        metadata.update(self.adapter.last_metadata)
        metadata["data_quality"] = self.adapter.last_metadata.get("data_quality", {
            "provider": "massive", "symbol": "XAUUSD", "timeframe": Timeframe(timeframe).value,
            "row_count": len(rows), "duplicate_timestamps": 0, "invalid_ohlc_rows": 0,
            "missing_interval_count": 0,
        })
        self._metadata[key] = metadata
        return candles

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Candle:
        raise NotImplementedError("Massive latest-candle access is not implemented; use historical aggregates.")

    async def subscribe(self, symbol: str, callback: Callable[[MarketEvent], None]) -> Subscription:
        raise NotImplementedError("Massive real-time subscription is not implemented by this adapter.")

    def get_dataset_metadata(self, symbol: str = "XAUUSD", timeframe: Timeframe = Timeframe.M5) -> dict[str, Any]:
        return dict(self._metadata.get((symbol.upper(), Timeframe(timeframe).value), {}))

    async def test_connection(self, *, start: datetime | None = None, end: datetime | None = None, timeframe: Timeframe = Timeframe.M5) -> dict[str, Any]:
        if not self.adapter.api_key:
            return {"status": "CONFIGURATION_ERROR", "message": "MASSIVE_API_KEY is not configured."}
        end_utc = _parse_iso_datetime(end) if end else datetime.now(timezone.utc)
        start_utc = _parse_iso_datetime(start) if start else end_utc - timedelta(days=5)
        try:
            candles = await self.get_historical_candles("XAUUSD", timeframe, start_utc, end_utc)
        except MassiveProviderError as exc:
            return {
                "status": exc.code,
                "message": str(exc),
                "http_status": exc.status_code,
                "data_quality": exc.data_quality,
            }
        except ValueError as exc:
            return {"status": "CAPABILITY_UNAVAILABLE", "message": str(exc)}
        if not candles:
            return {"status": "SYMBOL_UNAVAILABLE", "message": "Massive returned no XAUUSD aggregate bars for the requested range."}
        return {"status": "CONNECTED", "symbol": "XAUUSD", "provider_symbol": "C:XAUUSD", "timeframe": Timeframe(timeframe).value, "candle_count": len(candles)}


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


def create_market_data_provider(provider: str, **kwargs: Any) -> MarketDataProvider:
    """Build one of the repository's current provider implementations by name."""
    normalized = provider.strip().lower()
    symbol = kwargs.pop("symbol", "XAUUSD")
    if normalized == "massive":
        return MassiveDataProvider(symbol=symbol, **kwargs)
    if normalized == "mock":
        return MockDataProvider(symbol=symbol, **kwargs)
    if normalized == "free":
        return FreeHistoricalDataProvider(**kwargs)
    if normalized == "tradingview":
        return TradingViewDataProvider()
    if normalized == "broker":
        return BrokerDataProvider()
    raise ValueError(f"Unknown market-data provider {provider!r}.")


__all__ = [
    "BrokerDataProvider",
    "CsvHistoricalAdapter",
    "FreeHistoricalDataProvider",
    "HistoricalDataAdapter",
    "JsonHistoricalAdapter",
    "MarketDataProvider",
    "MarketEvent",
    "MassiveDataProvider",
    "MassiveHistoricalAdapter",
    "MassiveProviderError",
    "DataQualityReport",
    "create_market_data_provider",
    "MockDataProvider",
    "Subscription",
    "TradingViewDataProvider",
]
