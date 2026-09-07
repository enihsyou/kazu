from __future__ import annotations

from collections.abc import Iterator

from prometheus_client import CollectorRegistry
from prometheus_client.core import CounterMetricFamily

from kazu.lib.traffic import SubscriptionTrafficUsage

_SUBSCRIPTION_TRAFFIC_METRICS = (
    (
        "kazu_subscription_traffic_upload_bytes",
        "upload_bytes",
        "Current business-day cumulative subscription upload traffic in bytes.",
    ),
    (
        "kazu_subscription_traffic_download_bytes",
        "download_bytes",
        "Current business-day cumulative subscription download traffic in bytes.",
    ),
    (
        "kazu_subscription_traffic_deducted_bytes",
        "deducted_bytes",
        "Current business-day cumulative subscription deducted traffic in bytes.",
    ),
)
_SUBSCRIPTION_TRAFFIC_LABELS = ("provider", "user_id", "server_rate")


class SubscriptionTrafficMetrics:
    """Expose each upstream snapshot as daily counters."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._usages: tuple[SubscriptionTrafficUsage, ...] = ()
        registry.register(self)

    def update(self, usages: tuple[SubscriptionTrafficUsage, ...]) -> None:
        """Replace all previous label sets and values with the current snapshot."""
        self._usages = usages

    def collect(self) -> Iterator[CounterMetricFamily]:
        if not self._usages:
            return
        for name, attribute, description in _SUBSCRIPTION_TRAFFIC_METRICS:
            counter = CounterMetricFamily(name, description, labels=_SUBSCRIPTION_TRAFFIC_LABELS)
            for usage in self._usages:
                labels = [usage.provider, usage.user_id, usage.server_rate]
                value = getattr(usage, attribute)
                counter.add_metric(labels, value)
            yield counter
