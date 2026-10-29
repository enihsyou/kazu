"""Metric definitions and the shared factory for measurement values."""

from __future__ import annotations

from dataclasses import dataclass

from kazu.lib.usage import Measurement


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    help: str
    metric_type: str = "gauge"

    def create(self, value: float, **labels: str) -> Measurement:
        return Measurement(self.name, self.help, value, tuple(labels.items()), self.metric_type)


MONEY_REMAINING = MetricDefinition(
    "kazu_search_money_remaining", "Available account balance in the labeled currency."
)
CREDITS_REMAINING = MetricDefinition(
    "kazu_search_credits_remaining", "Available credits in the selected scope."
)
CREDITS_CAP = MetricDefinition(
    "kazu_search_credits_cap", "Credit allowance for the selected scope."
)
CREDITS_USED = MetricDefinition("kazu_search_credits_used", "Credits used in the selected scope.")
CALLS_USED = MetricDefinition(
    "kazu_search_calls_used", "Number of search requests in the selected scope."
)
SOURCE_UP = MetricDefinition("kazu_source_up", "Whether the latest query fully succeeded.")
SOURCE_WATCHING = MetricDefinition("kazu_source_watching", "Whether background polling is active.")
SOURCE_LAST_SUCCESS = MetricDefinition(
    "kazu_source_last_success_timestamp_seconds", "Unix timestamp of the last successful query."
)
SOURCE_QUERY_DURATION = MetricDefinition(
    "kazu_source_query_duration_seconds", "Duration of the latest query."
)
TRAFFIC_METRICS = {
    field: MetricDefinition(
        f"kazu_subscription_traffic_{field}_bytes",
        f"Current business-day cumulative subscription {field} traffic in bytes.",
        metric_type="counter",
    )
    for field in ("upload", "download", "deducted")
}
