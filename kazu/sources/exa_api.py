"""Exa Team Management usage; requires service access and a Service Key."""

from __future__ import annotations

import math

from kazu.config import ExaConfig, SourceConfig
from kazu.lib.measurements import MONEY_USED
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources.api_http import get_json


def collect(config: SourceConfig) -> UsageSnapshot:
    if (
        not isinstance(config, ExaConfig)
        or not isinstance(config.service_key, str)
        or not config.service_key.strip()
    ):
        raise CollectionError("EXA_SERVICE_KEY is required; Exa service access must be enabled")
    if not config.api_key_id:
        raise CollectionError("sources.exa.api_key_id is required")

    # No date parameters: Exa defaults to the last 30 days ending now.
    data = get_json(
        f"https://admin-api.exa.ai/team-management/api-keys/{config.api_key_id}/usage",
        headers={"x-api-key": config.service_key},
        timeout=config.timeout,
    )
    try:
        value = data["total_cost_usd"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise CollectionError("Exa usage response has invalid total_cost_usd") from None

    return UsageSnapshot((MONEY_USED.create(value, currency="USD", scope="key_30d"),))
