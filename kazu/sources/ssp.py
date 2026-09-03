"""SSP collection and normalization, independent of CLI and export transports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

from kazu.config import SSPConfig
from kazu.lib.sspgateway import SSPGateway, SSPGatewayError, TraceCallback, TrafficRecord
from kazu.lib.traffic import SubscriptionTrafficUsage, TrafficCollectionError, TrafficSnapshot


@dataclass(frozen=True)
class SSPTrafficReport:
    """Traffic records collected from SSP with source metadata."""

    domain: str
    """Configured source domain."""
    account: str
    """Account label associated with the records."""
    extracted_at: datetime
    """Timestamp when the report was extracted."""
    records: tuple[TrafficRecord, ...]
    """Traffic records returned by SSP."""


def normalize_traffic(
    records: tuple[TrafficRecord, ...], today: date
) -> tuple[SubscriptionTrafficUsage, ...]:
    """Build validated daily usage values from SSP traffic records."""
    usages: dict[tuple[str, date], SubscriptionTrafficUsage] = {}
    for record in records:
        usage = _daily_usage(record)
        if usage.usage_date > today:
            raise ValueError(f"SSP returned a future usage date: {usage.usage_date.isoformat()}")
        key = (usage.user_id, usage.usage_date)
        existing = usages.get(key)
        if existing is not None and existing != usage:
            raise ValueError(
                "SSP returned conflicting traffic records for "
                f"user_id={usage.user_id}, usage_date={usage.usage_date.isoformat()}"
            )
        usages[key] = usage
    return tuple(sorted(usages.values(), key=lambda item: (item.usage_date, item.user_id)))


def _daily_usage(record: TrafficRecord) -> SubscriptionTrafficUsage:
    user_id = str(record.user_id).strip()
    if not user_id or "\n" in user_id or "\r" in user_id:
        raise ValueError("SSP traffic record contains an invalid user_id")
    if record.upload_bytes < 0 or record.download_bytes < 0:
        raise ValueError("SSP traffic record contains negative traffic bytes")
    if not record.multiplier.is_finite() or record.multiplier < 0:
        raise ValueError("SSP traffic record contains an invalid server_rate")
    total = record.upload_bytes + record.download_bytes
    deducted = int(
        (Decimal(total) * record.multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return SubscriptionTrafficUsage(
        provider="ssp",
        user_id=user_id,
        usage_date=record.recorded_at.astimezone().date(),
        server_rate=_server_rate_text(record),
        upload_bytes=record.upload_bytes,
        download_bytes=record.download_bytes,
        deducted_bytes=deducted,
    )


def _server_rate_text(record: TrafficRecord) -> str:
    raw_value = record.raw.get("server_rate")
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip()
    return format(record.multiplier, "f")


class SSPSource:
    """Collect traffic reports and normalized usage snapshots from SSP."""

    def __init__(
        self,
        config: SSPConfig,
        *,
        authorization: str | None = None,
        timeout: float | None = None,
        trace: TraceCallback | None = None,
    ) -> None:
        self._domain = config.domain or "ssp"
        self._gateway = SSPGateway(
            config.authorization if authorization is None else authorization,
            api_base_url=config.api_base_url,
            traffic_endpoint=config.traffic_endpoint,
            gateway_endpoints=config.gateway_endpoints,
            timeout=config.timeout if timeout is None else timeout,
            trace=trace,
        )

    def __enter__(self) -> Self:
        """Enter the source context and return this source instance."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the source when leaving its context."""
        self.close()

    def close(self) -> None:
        """Release the underlying SSP gateway resources."""
        self._gateway.close()

    def fetch_report(self) -> SSPTrafficReport:
        """Fetch the latest traffic report from SSP."""
        try:
            traffic = self._gateway.get_traffic_log()
        except (SSPGatewayError, ValueError) as exc:
            raise TrafficCollectionError(f"Unable to fetch SSP traffic: {exc}") from exc
        return SSPTrafficReport(
            domain=self._domain,
            account=f"{traffic.records[0].user_id}" if traffic.records else "unknown",
            extracted_at=datetime.now().astimezone(),
            records=traffic.records,
        )

    def collect(self) -> TrafficSnapshot:
        """Collect and normalize the latest SSP traffic snapshot."""
        report = self.fetch_report()
        try:
            usages = normalize_traffic(report.records, report.extracted_at.date())
        except ValueError as exc:
            raise TrafficCollectionError(f"Unable to normalize SSP traffic: {exc}") from exc
        return TrafficSnapshot(observed_at=report.extracted_at, usages=usages)
