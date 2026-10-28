"""Map SSP daily traffic snapshots to their existing Prometheus counters."""

from __future__ import annotations

from kazu.lib.measurements import TRAFFIC_METRICS
from kazu.lib.traffic import SubscriptionTrafficUsage
from kazu.lib.usage import Measurement


def traffic_measurements(usages: tuple[SubscriptionTrafficUsage, ...]) -> tuple[Measurement, ...]:
    return tuple(
        definition.create(
            getattr(usage, f"{field}_bytes"),
            user_id=usage.user_id,
            server_rate=usage.server_rate,
        )
        for usage in usages
        for field, definition in TRAFFIC_METRICS.items()
    )
