from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge, generate_latest

from kazu.lib.traffic import SubscriptionTrafficUsage

_METRICS = (
    (
        "proxy_traffic_upload_bytes",
        "upload_bytes",
        "Current business-day cumulative subscription upload traffic in bytes.",
    ),
    (
        "proxy_traffic_download_bytes",
        "download_bytes",
        "Current business-day cumulative subscription download traffic in bytes.",
    ),
    (
        "proxy_traffic_deducted_bytes",
        "deducted_bytes",
        "Current business-day cumulative subscription deducted traffic in bytes.",
    ),
)
_LABELS = ("provider", "user_id", "server_rate")


def render_traffic_metrics(usages: tuple[SubscriptionTrafficUsage, ...]) -> bytes:
    """Render the supplied usages as Prometheus exposition bytes."""
    registry = CollectorRegistry()
    for name, attribute, description in _METRICS:
        gauge = Gauge(name, description, labelnames=_LABELS, registry=registry)
        for usage in usages:
            gauge.labels(
                provider=usage.provider,
                user_id=usage.user_id,
                server_rate=usage.server_rate,
            ).set(getattr(usage, attribute))
    return generate_latest(registry)
