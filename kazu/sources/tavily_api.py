"""Collect credit usage from Tavily's authenticated usage endpoint."""

from __future__ import annotations

import math
from typing import Any

from kazu.config import SourceConfig
from kazu.lib.measurements import CREDITS_CAP, CREDITS_REMAINING, CREDITS_USED
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources.api_http import get_json


def _credits(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError
    return value


def _parse_usage(data: dict[str, Any]) -> UsageSnapshot:
    try:
        key, account = data["key"], data["account"]
        if not isinstance(key, dict) or not isinstance(account, dict):
            raise ValueError
        # Endpoint-specific usage is also credits, not a count of requests.
        scopes = (
            ("key", key["usage"], key["limit"]),
            ("plan", account["plan_usage"], account["plan_limit"]),
            ("paygo", account["paygo_usage"], account["paygo_limit"]),
        )
        measurements = []
        for scope, usage, limit in scopes:
            used = _credits(usage)
            measurements.append(CREDITS_USED.create(used, scope=scope))
            # Only the key limit can be null, meaning unlimited rather than zero.
            if scope == "key" and limit is None:
                continue
            cap = _credits(limit)
            measurements.extend(
                (
                    CREDITS_CAP.create(cap, scope=scope),
                    CREDITS_REMAINING.create(max(cap - used, 0), scope=scope),
                )
            )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise CollectionError("Tavily usage response has an invalid schema") from None
    return UsageSnapshot(tuple(measurements))


def collect(config: SourceConfig) -> UsageSnapshot:
    if not isinstance(config.api_key, str) or not config.api_key.strip():
        raise CollectionError("Tavily API key is required")
    data = get_json(
        "https://api.tavily.com/usage",
        headers={"Authorization": f"Bearer {config.api_key}"},
        timeout=config.timeout,
    )
    return _parse_usage(data)
