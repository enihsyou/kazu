from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Lock

from kazu.lib.metrics.traffic import render_traffic_metrics
from kazu.lib.traffic import TrafficCollectionError, TrafficSnapshot, TrafficSource

_LOGGER = logging.getLogger(__name__)


class MetricsUnavailable(RuntimeError):
    """No fresh metrics can be served for this scrape."""


class TrafficExporter:
    """Collect once per scrape, with an optional independent persistence observer."""

    def __init__(
        self,
        source: TrafficSource,
        *,
        on_collect: Callable[[TrafficSnapshot], None] | None = None,
    ) -> None:
        self._source = source
        self._on_collect = on_collect
        self._lock = Lock()

    def render(self) -> bytes:
        """Collect a fresh snapshot and render its current metrics."""
        # Reject overlapping scrapes instead of queuing upstream requests and writes.
        if not self._lock.acquire(blocking=False):
            raise MetricsUnavailable("A traffic collection is already in progress.")
        try:
            return self._collect_metrics()
        finally:
            self._lock.release()

    def _collect_metrics(self) -> bytes:
        try:
            snapshot = self._source.collect()
        except TrafficCollectionError as exc:
            _LOGGER.error("Metrics collection failed: %s", exc)
            raise MetricsUnavailable("Unable to collect fresh traffic metrics.") from exc

        if self._on_collect is not None:
            self._on_collect(snapshot)
        current = snapshot.current_usages
        if not current:
            _LOGGER.warning("The source returned no traffic for today's local business date.")
            raise MetricsUnavailable("No traffic record for today's local business date.")
        return render_traffic_metrics(current)
