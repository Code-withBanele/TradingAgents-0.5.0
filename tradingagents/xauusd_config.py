from __future__ import annotations

from typing import Any

XAUUSD_CONFIG: dict[str, Any] = {
    "symbol": "XAUUSD",
    "provider": "massive",
    "provider_symbol": "C:XAUUSD",
    "trading_mode": "paper",
    "live_trading": False,
    "default_timeframe": "5m",
    "supported_timeframes": ["1m", "5m"],
    "execution_mode": "paper",
    "asset_class": "spot_gold",
    "market_session": "london_new_york",
    "risk_guardrails": {
        "spread_limit": 0.0,
        "max_daily_trades": 0,
    },
}

__all__ = ["XAUUSD_CONFIG"]
