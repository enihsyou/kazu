from datetime import UTC, date, datetime

import pytest

from kazu.lib.influxdb3.client import InfluxDB3Error
from kazu.lib.influxdb3.traffic import InfluxDB3SubscriptionTrafficWriter
from kazu.lib.traffic import SubscriptionTrafficSnapshot, SubscriptionTrafficUsage


class FakeClient:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.queries: list[tuple[str, dict[str, str] | None]] = []
        self.writes: list[list[str]] = []
        self.write_error: Exception | None = None

    def query(self, query: str, params: dict[str, str] | None = None) -> list[dict[str, object]]:
        self.queries.append((query, params))
        return self.rows

    def write_lines(self, lines: list[str]) -> None:
        if self.write_error is not None:
            raise self.write_error
        self.writes.append(lines)


def _usage(usage_date: date, *, upload_bytes: int = 10) -> SubscriptionTrafficUsage:
    return SubscriptionTrafficUsage(
        provider="ssp",
        user_id="123",
        usage_date=usage_date,
        server_rate="1.5",
        upload_bytes=upload_bytes,
        download_bytes=20,
        deducted_bytes=45,
    )


def _snapshot(*usages: SubscriptionTrafficUsage) -> SubscriptionTrafficSnapshot:
    return SubscriptionTrafficSnapshot(
        observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        usages=usages,
    )


def test_table_exists_is_an_explicit_single_query() -> None:
    client = FakeClient()
    client.rows = [{"table_name": "subscription_traffic_daily"}]
    writer = InfluxDB3SubscriptionTrafficWriter(client)  # type: ignore[arg-type]

    assert writer.table_exists() is True
    assert len(client.queries) == 1
    assert "information_schema.tables" in client.queries[0][0]


def test_write_uses_memory_for_historical_final_without_queries() -> None:
    client = FakeClient()
    writer = InfluxDB3SubscriptionTrafficWriter(client)  # type: ignore[arg-type]
    usage = _usage(date(2026, 9, 5))
    snapshot = _snapshot(usage)

    assert writer.write(snapshot) == 1
    assert writer.write(snapshot) == 0

    assert client.queries == []
    assert len(client.writes) == 2
    assert len(client.writes[0]) == 1
    assert client.writes[1] == []


def test_different_in_memory_historical_final_is_rejected() -> None:
    client = FakeClient()
    writer = InfluxDB3SubscriptionTrafficWriter(client)  # type: ignore[arg-type]
    writer.write(_snapshot(_usage(date(2026, 9, 5))))

    with pytest.raises(InfluxDB3Error, match="different historical daily final"):
        writer.write(_snapshot(_usage(date(2026, 9, 5), upload_bytes=11)))


def test_failed_write_does_not_record_historical_final() -> None:
    client = FakeClient()
    writer = InfluxDB3SubscriptionTrafficWriter(client)  # type: ignore[arg-type]
    snapshot = _snapshot(_usage(date(2026, 9, 5)))
    client.write_error = InfluxDB3Error("unavailable")

    with pytest.raises(InfluxDB3Error, match="unavailable"):
        writer.write(snapshot)

    client.write_error = None
    assert writer.write(snapshot) == 1
    assert len(client.writes) == 1
