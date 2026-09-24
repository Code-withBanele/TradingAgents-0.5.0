"""Forex Factory economic-calendar vendor.

This is intentionally a macro-evidence provider, not a trading execution engine.
It normalizes upcoming scheduled releases into a deterministic, analyst-friendly
summary that can be used to assess whether the current fundamental environment
for XAUUSD is likely to be invalidated by data surprises, central-bank moves,
or broader macro risk.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from .errors import VendorNotConfiguredError
from .utils import get_scrubbed

logger = logging.getLogger(__name__)

FOREX_FACTORY_BASE = "https://www.forexfactory.com"
REQUEST_TIMEOUT = 30
DEFAULT_LIMIT = 12


class ForexFactoryNotConfiguredError(VendorNotConfiguredError):
    """Raised when the Forex Factory path is selected without any configuration."""


def _calendar_url(curr_date: str | None = None) -> str:
    """Return the calendar endpoint for the relevant date window."""
    date = curr_date or datetime.utcnow().strftime("%Y-%m-%d")
    return f"{FOREX_FACTORY_BASE}/calendar?day={date}"


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_relevance(instrument: str, title: str) -> str:
    """Rough relevance heuristic for XAUUSD / gold-themed macro context."""
    key = (instrument or "").strip().lower()
    text = (title or "").lower()
    if key in {"xauusd", "gold", "gc=f", "xau", "goldusd"}:
        gold_terms = {"gold", "precious", "commodity", "inflation", "cpi", "pce", "jobs", "fed", "us", "rate", "yield"}
        if any(term in text for term in gold_terms):
            return "high"
    if any(term in text for term in {"fed", "inflation", "cpi", "pce", "nonfarm", "jobs", "gdp", "trade", "central bank", "policy", "yield"}):
        return "medium"
    return "low"


def _normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw calendar row into a stable, evidence-oriented dict."""
    title = (raw.get("title") or raw.get("event") or raw.get("name") or "Macro event").strip()
    time_str = raw.get("time") or raw.get("event_time") or raw.get("date") or ""
    impact = (raw.get("impact") or raw.get("importance") or "low").lower()
    actual = raw.get("actual")
    forecast = raw.get("forecast")
    previous = raw.get("previous")
    source = raw.get("source") or raw.get("currency") or "Forex Factory"
    return {
        "title": title,
        "time": time_str,
        "impact": impact,
        "actual": actual,
        "forecast": forecast,
        "previous": previous,
        "source": source,
        "relevance": _event_relevance("XAUUSD", title),
    }


def get_economic_calendar(
    instrument: str,
    curr_date: str,
    limit: int | None = None,
) -> str:
    """Return upcoming macro events relevant to the instrument as markdown.

    Forex Factory exposes a public HTML calendar, but the content is not a stable
    API. This provider therefore scrapes the event table in a fail-open way,
    returning a structured summary instead of hard-failing the analysis when the
    site is unavailable.
    """
    if limit is None:
        limit = DEFAULT_LIMIT

    try:
        url = _calendar_url(curr_date)
        response = get_scrubbed(url, timeout=REQUEST_TIMEOUT, passthrough=(403, 404))
    except Exception as exc:  # pragma: no cover - network-spectrum fallback
        logger.warning("Forex Factory calendar fetch failed for %s: %s", instrument, exc)
        return (
            f"ECONOMIC_CALENDAR_UNAVAILABLE: Forex Factory calendar data could not be fetched "
            f"for {instrument} on {curr_date} ({exc}). Report the macro context as unavailable "
            f"without fabricating the event schedule."
        )

    if response.status_code in (403, 404):
        return (
            "ECONOMIC_CALENDAR_UNAVAILABLE: Forex Factory calendar is temporarily unavailable. "
            "Proceed without the event schedule; do not estimate or invent the macro calendar."
        )

    html = response.text or ""
    if not html:
        return "ECONOMIC_CALENDAR_UNAVAILABLE: Forex Factory returned an empty calendar payload."

    # Keep this deliberately narrow: decode any JSON-embedded calendar payload if
    # present, otherwise fall back to a simple text scan for event rows.
    try:
        # Some pages include an embedded script payload with event objects.
        marker = 'calendarData'
        start = html.find(marker)
        if start != -1:
            segment = html[start + len(marker):]
            json_start = segment.find("[")
            json_end = segment.rfind("]")
            if json_start != -1 and json_end > json_start:
                candidate = segment[json_start:json_end + 1]
                data = json.loads(candidate)
                if isinstance(data, list):
                    events = [
                        _normalize_event(event)
                        for event in data
                        if isinstance(event, dict)
                    ]
                    if events:
                        return _render_calendar(instrument, curr_date, events[:limit])
    except Exception:  # pragma: no cover - tolerant parsing
        logger.debug("Forex Factory embedded calendar payload was not JSON-like.", exc_info=True)

    rows = []
    for line in html.splitlines():
        cleaned = " ".join(line.strip().split())
        if any(token in cleaned.lower() for token in ["fed", "inflation", "nonfarm", "gdp", "cpi", "pce", "jobs", "employment", "policy", "central bank"]):
            rows.append(cleaned)

    events = [
        {"title": row, "time": "scheduled", "impact": "unknown", "actual": None, "forecast": None, "previous": None, "source": "Forex Factory", "relevance": _event_relevance(instrument, row)}
        for row in rows[:limit]
    ]
    return _render_calendar(instrument, curr_date, events)


def _render_calendar(instrument: str, curr_date: str, events: list[dict[str, Any]]) -> str:
    if not events:
        return (
            f"## Forex Factory economic calendar for {instrument} ({curr_date})\n"
            "No upcoming macro events were detected in the current calendar window."
        )

    lines = [
        f"## Forex Factory economic calendar for {instrument} ({curr_date})",
        "Upcoming macro releases that can invalidate or reinforce the current fundamental environment:",
    ]
    for idx, event in enumerate(events):
        title = event.get("title") or "Macro event"
        time_text = event.get("time") or "scheduled"
        impact = (event.get("impact") or "unknown").upper()
        relevance = (event.get("relevance") or "low").upper()
        actual = event.get("actual")
        forecast = event.get("forecast")
        previous = event.get("previous")
        extras = []
        if actual is not None:
            extras.append(f"actual: {actual}")
        if forecast is not None:
            extras.append(f"forecast: {forecast}")
        if previous is not None:
            extras.append(f"previous: {previous}")
        extras_text = f" | {' | '.join(extras)}" if extras else ""
        lines.append(f"- **{idx + 1}. {title}** — {time_text} | impact={impact} | relevance={relevance}{extras_text}")
    return "\n".join(lines) + "\n"
