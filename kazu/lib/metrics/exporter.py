"""Render immutable cached snapshots; Prometheus never waits for provider I/O."""

from __future__ import annotations

from collections.abc import Iterator

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric

from kazu.lib.measurements import (
    SOURCE_LAST_SUCCESS,
    SOURCE_QUERY_DURATION,
    SOURCE_UP,
    SOURCE_WATCHING,
)
from kazu.lib.metrics.watch import SourceWatch


class MetricsExporter:
    def __init__(self, watches: dict[str, SourceWatch]) -> None:
        self.watches = watches
        self.registry = CollectorRegistry()
        self.registry.register(self)

    def describe(self) -> list[Metric]:
        # Registration must not count as a scrape or wake a paused source.
        return []

    def collect(self) -> Iterator[Metric]:
        families = {}
        for provider, watch in self.watches.items():
            view = watch.consume()
            values = [
                SOURCE_UP.create(float(view.success)),
                SOURCE_WATCHING.create(float(view.watching)),
                SOURCE_LAST_SUCCESS.create(view.last_success),
                SOURCE_QUERY_DURATION.create(view.duration),
            ]
            if view.snapshot is not None:
                values.extend(view.snapshot.measurements)
            for value in values:
                if value.name not in families:
                    metric_type = (
                        CounterMetricFamily if value.metric_type == "counter" else GaugeMetricFamily
                    )
                    families[value.name] = metric_type(
                        value.name, value.help, labels=["provider", *[k for k, _ in value.labels]]
                    )
                families[value.name].add_metric(
                    [provider, *[v for _, v in value.labels]], value.value
                )
        yield from families.values()

    def render(self) -> bytes:
        return generate_latest(self.registry)
