from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge

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
    """Own reusable subscription traffic gauges for one exporter instance."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._gauges = {
            attribute: Gauge(
                name, description, labelnames=_SUBSCRIPTION_TRAFFIC_LABELS, registry=registry
            )
            for name, attribute, description in _SUBSCRIPTION_TRAFFIC_METRICS
        }

    def update(self, usages: tuple[SubscriptionTrafficUsage, ...]) -> None:
        """Replace all previous label sets and values with the current snapshot."""
        for attribute, gauge in self._gauges.items():
            gauge.clear()
            for usage in usages:
                gauge.labels(
                    provider=usage.provider,
                    user_id=usage.user_id,
                    server_rate=usage.server_rate,
                ).set(getattr(usage, attribute))
