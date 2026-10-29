"""Firecrawl team credit balance without inferring spending from top-up credits."""

from __future__ import annotations

import math
from typing import Any

from kazu.config import SourceConfig
from kazu.lib.measurements import CREDITS_CAP, CREDITS_REMAINING
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources.api_http import get_json


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError
    return float(value)


def collect(config: SourceConfig) -> UsageSnapshot:
    if not config.api_key.strip():
        raise CollectionError("FIRECRAWL_API_KEY is required")
    result = get_json(
        "https://api.firecrawl.dev/v2/team/credit-usage",
        headers={"Authorization": f"Bearer {config.api_key}"},
        timeout=config.timeout,
    )
    try:
        if result["success"] is not True:
            raise ValueError
        data = result["data"]
        if not isinstance(data, dict):
            raise ValueError
        remaining = _number(data["remainingCredits"])
        plan = _number(data["planCredits"])
    except (KeyError, TypeError, ValueError, OverflowError):
        raise CollectionError("Unexpected Firecrawl credit response schema") from None

    measurements = [CREDITS_REMAINING.create(remaining, scope="account")]
    if plan > 0:
        measurements.append(CREDITS_CAP.create(plan, scope="plan"))
    # Remaining credits include top-ups, so plan minus remaining is not usage.
    return UsageSnapshot(tuple(measurements))
