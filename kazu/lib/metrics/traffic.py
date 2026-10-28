"""Map SSP daily traffic snapshots to their existing Prometheus counters."""

from __future__ import annotations

from kazu.lib.traffic import SubscriptionTrafficUsage
from kazu.lib.usage import Measurement


def traffic_measurements(usages: tuple[SubscriptionTrafficUsage, ...]) -> tuple[Measurement, ...]:
    return tuple(
        Measurement(
            f"kazu_subscription_traffic_{field}_bytes",
            f"Current business-day cumulative subscription {field} traffic in bytes.",
            getattr(usage, f"{field}_bytes"),
            (("user_id", usage.user_id), ("server_rate", usage.server_rate)),
            kind="counter",
        )
        for usage in usages
        for field in ("upload", "download", "deducted")
    )
