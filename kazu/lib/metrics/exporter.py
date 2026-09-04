from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Lock

from prometheus_client import CollectorRegistry, generate_latest

from kazu.lib.metrics.traffic import SubscriptionTrafficMetrics
from kazu.lib.traffic import SubscriptionTrafficCollectionError, SubscriptionTrafficSnapshot

_LOGGER = logging.getLogger(__name__)


class MetricsUnavailable(RuntimeError):
    """No fresh metrics can be served for this scrape."""


class SubscriptionTrafficExporter:
    """Collect once per scrape, with an optional independent persistence observer."""

    def __init__(
        self,
        collect: Callable[[], SubscriptionTrafficSnapshot],
        *,
        registry: CollectorRegistry,
        on_collect: Callable[[SubscriptionTrafficSnapshot], None] | None = None,
    ) -> None:
        self._collect = collect
        self._registry = registry
        self._subscription_traffic_metrics = SubscriptionTrafficMetrics(registry)
        self._on_collect = on_collect
        self._lock = Lock()

    def render(self) -> bytes:
        """Collect a fresh snapshot and render its current metrics."""
        # Reject overlapping scrapes instead of queuing upstream requests and writes.
        if not self._lock.acquire(blocking=False):
            raise MetricsUnavailable("# A traffic collection is already in progress.")
        try:
            self._collect_metrics()
            return generate_latest(self._registry)
        finally:
            self._lock.release()

    def _collect_metrics(self) -> None:
        try:
            snapshot = self._collect()
        except SubscriptionTrafficCollectionError as exc:
            _LOGGER.error("Metrics collection failed: %s", exc)
            raise MetricsUnavailable("Unable to collect fresh traffic metrics.") from exc

        if self._on_collect is not None:
            self._on_collect(snapshot)
        current = snapshot.current_usages
        if not current:
            _LOGGER.warning("The source returned no traffic for today's local business date.")
            raise MetricsUnavailable("No traffic record for today's local business date.")
        self._subscription_traffic_metrics.update(current)
