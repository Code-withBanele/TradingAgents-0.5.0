from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def _json_default(value: Any) -> Any:
    """Convert values that are not JSON-native into a deterministic string."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (set, tuple)):
        return sorted(value)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)


def _prompt_text(prompt_inputs: Any) -> str:
    if isinstance(prompt_inputs, str):
        return prompt_inputs
    return _canonical_json(prompt_inputs)


def _cache_key(model: str, strategy_version: str, prompt_inputs: Any) -> str:
    payload = _canonical_json({
        "model": model,
        "strategy_version": strategy_version,
        "prompt_inputs": prompt_inputs,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _connect_cache(path: str | Path) -> sqlite3.Connection:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cache_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_reliability_cache (
            cache_key TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            strategy_version TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _read_cached_result(cache_path: str | Path | None, cache_key: str) -> Any | None:
    if cache_path is None:
        return None
    with _connect_cache(cache_path) as conn:
        row = conn.execute(
            "SELECT payload FROM llm_reliability_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        return payload


def _write_cached_result(cache_path: str | Path | None, cache_key: str, model: str, strategy_version: str, payload: Any) -> None:
    if cache_path is None:
        return
    with _connect_cache(cache_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_reliability_cache (cache_key, model, strategy_version, payload, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (cache_key, model, strategy_version, _canonical_json(payload)),
        )
        conn.commit()


def _validate_schema(payload: Any, schema: type[T] | None) -> dict[str, Any] | None:
    if schema is None:
        if isinstance(payload, dict):
            return payload
        if payload is None:
            return None
        return payload

    if isinstance(payload, schema):
        return payload.model_dump(mode="json")

    if isinstance(payload, dict):
        validated = schema.model_validate(payload)
        return validated.model_dump(mode="json")

    if hasattr(payload, "model_dump"):
        validated = schema.model_validate(payload.model_dump(mode="json"))
        return validated.model_dump(mode="json")

    raise ValidationError.from_exception_data(
        title=schema.__name__,
        line_errors=[],
    )


def call_with_llm_reliability(
    *,
    model: str,
    strategy_version: str,
    prompt_inputs: Any,
    invoke_fn: Callable[[Any], Any],
    schema: type[T] | None = None,
    cache_path: str | Path | None = None,
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.25,
) -> dict[str, Any] | None:
    """Invoke an LLM-like function with a persistence-backed cache and fail-closed semantics.

    The default contract is intentionally conservative: malformed output or any
    exception yields ``None`` rather than letting downstream code proceed with a
    speculative result.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")

    key = _cache_key(model, strategy_version, prompt_inputs)
    cached = _read_cached_result(cache_path, key)
    if cached is not None:
        try:
            return _validate_schema(cached, schema)
        except Exception:
            return cached if schema is None else None

    prompt = _prompt_text(prompt_inputs)
    backoff = float(retry_backoff_seconds)
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            result = invoke_fn(prompt)
            validated = _validate_schema(result, schema)
            if validated is None:
                raise ValueError("LLM response was empty or malformed")
            if cache_path is not None:
                _write_cached_result(cache_path, key, model, strategy_version, validated)
            return validated
        except Exception as exc:  # noqa: BLE001 - fail closed by design
            last_error = exc
            if attempt >= max_retries:
                break
            if backoff > 0:
                time.sleep(backoff)
            backoff *= 2.0

    return None


__all__ = ["call_with_llm_reliability"]
