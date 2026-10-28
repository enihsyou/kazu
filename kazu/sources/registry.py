"""Wire enabled sources without coupling the exporter to provider details."""

from __future__ import annotations

from kazu.config import AppConfig, SourceConfig
from kazu.lib.metrics.traffic import traffic_measurements
from kazu.lib.sspgateway import SSPGatewayError
from kazu.lib.traffic import SubscriptionTrafficCollectionError
from kazu.lib.usage import CollectionError, UsageSnapshot, UsageSource
from kazu.sources.search import SearchSource
from kazu.sources.ssp import SSPSource


class SSPMetricsSource:
    mode = "api"

    def __init__(self, config: AppConfig) -> None:
        self._config = config.ssp
        self._source: SSPSource | None = None

    def collect(self) -> UsageSnapshot:
        if self._config.source == "cli":
            raise CollectionError("SSP metrics use the built-in API source")
        if not self._config.authorization:
            raise CollectionError("SSP_AUTHORIZATION is required")
        try:
            if self._source is None:
                self._source = SSPSource(self._config)
            snapshot = self._source.collect()
        except (SSPGatewayError, SubscriptionTrafficCollectionError, ValueError) as exc:
            raise CollectionError(f"SSP query failed ({type(exc).__name__})") from exc
        return UsageSnapshot(
            traffic_measurements(snapshot.current_usages), snapshot.observed_at.timestamp()
        )

    def close(self) -> None:
        if self._source is not None:
            self._source.close()


def source_configs(config: AppConfig) -> dict[str, SourceConfig]:
    return {"ssp": config.ssp, **config.providers}


def create_source(name: str, config: AppConfig) -> UsageSource:
    if name == "ssp":
        return SSPMetricsSource(config)
    return SearchSource(name, config.providers[name])
