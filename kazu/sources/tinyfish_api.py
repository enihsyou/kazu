"""TinyFish wallet balance and historical search count from the official CLI APIs."""

from __future__ import annotations

import math

from kazu.config import SourceConfig
from kazu.lib.measurements import CALLS_USED, MONEY_REMAINING
from kazu.lib.redaction import redact
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources.api_http import get_json


def collect(config: SourceConfig) -> UsageSnapshot:
    if not config.api_key.strip():
        raise CollectionError("TINYFISH_API_KEY is required")
    headers = {"X-API-Key": config.api_key}
    measurements = []
    warnings = []
    # Legacy credit accounts have no wallet; search history remains independently useful.
    for query in ("wallet", "search"):
        try:
            if query == "wallet":
                data = get_json(
                    "https://agent.tinyfish.ai/v1/wallet",
                    headers=headers,
                    timeout=config.timeout,
                )
                balance, currency = data["available_balance"], data["currency"]
                if not isinstance(balance, str) or not isinstance(currency, str) or not currency:
                    raise ValueError
                balance = float(balance)
                if not math.isfinite(balance):
                    raise ValueError
                # Wallet balances are signed: overdrawn accounts must remain negative.
                measurements.append(
                    MONEY_REMAINING.create(balance, currency=currency, scope="account")
                )
            else:
                data = get_json(
                    "https://agent.tinyfish.ai/v1/search/usage",
                    headers=headers,
                    timeout=config.timeout,
                    params={"limit": 1},
                )
                total = data["total"]
                if (
                    isinstance(total, bool)
                    or not isinstance(total, (int, float))
                    or not math.isfinite(total)
                    or total < 0
                ):
                    raise ValueError
                measurements.append(CALLS_USED.create(float(total), scope="all_time"))
        except CollectionError as exc:
            warnings.append(f"{query}: {redact(str(exc), headers)}")
        except (KeyError, TypeError, ValueError, OverflowError):
            warnings.append(f"{query}: Unexpected API response schema")
    if not measurements:
        raise CollectionError("; ".join(warnings))
    return UsageSnapshot(tuple(measurements), warnings=tuple(warnings))
