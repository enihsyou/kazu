"""Render immutable cached snapshots; Prometheus never waits for provider I/O."""

from __future__ import annotations

from collections.abc import Iterator

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric

from kazu.lib.metrics.watch import SourceWatch
from kazu.lib.usage import Measurement


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
                Measurement(
                    "kazu_source_up",
                    "Whether the latest query fully succeeded.",
                    float(view.success),
                ),
                Measurement(
                    "kazu_source_watching",
                    "Whether background polling is active.",
                    float(view.watching),
                ),
                Measurement(
                    "kazu_source_last_success_timestamp_seconds",
                    "Unix timestamp of the last successful query.",
                    view.last_success,
                ),
                Measurement(
                    "kazu_source_query_duration_seconds",
                    "Duration of the latest query.",
                    view.duration,
                ),
            ]
            if view.snapshot is not None:
                values.extend(view.snapshot.measurements)
            for value in values:
                if value.name not in families:
                    metric_type = (
                        CounterMetricFamily if value.kind == "counter" else GaugeMetricFamily
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
