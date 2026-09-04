from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from kazu.lib.influxdb3.client import InfluxDB3Client, InfluxDB3Error
from kazu.lib.traffic import SubscriptionTrafficSnapshot, SubscriptionTrafficUsage

_SUBSCRIPTION_TRAFFIC_TABLE = "subscription_traffic_daily"


def encode_subscription_traffic_usage(
    usage: SubscriptionTrafficUsage, observed_at: datetime
) -> str:
    """Encode one traffic usage as an InfluxDB line-protocol record."""
    tags = f"provider={_tag(usage.provider)},user_id={_tag(usage.user_id)}"
    fields = (
        f"upload_bytes={usage.upload_bytes}u,"
        f"download_bytes={usage.download_bytes}u,"
        f"deducted_bytes={usage.deducted_bytes}u,"
        f'server_rate="{_field_string(usage.server_rate)}",'
        f'usage_date="{usage.usage_date.isoformat()}"'
    )
    timestamp = (
        observed_at
        if usage.usage_date == observed_at.astimezone().date()
        else daily_final_time(usage.usage_date)
    )
    nanoseconds = int(timestamp.timestamp()) * 1_000_000_000 + timestamp.microsecond * 1_000
    return f"{_SUBSCRIPTION_TRAFFIC_TABLE},{tags} {fields} {nanoseconds}"


def decode_subscription_traffic_usage(
    row: dict[str, Any], expected: SubscriptionTrafficUsage
) -> SubscriptionTrafficUsage:
    """Decode one InfluxDB row into a traffic usage value."""
    try:
        return SubscriptionTrafficUsage(
            provider=expected.provider,
            user_id=expected.user_id,
            usage_date=date.fromisoformat(_string(row["usage_date"])),
            server_rate=_string(row["server_rate"]),
            upload_bytes=_integer(row["upload_bytes"]),
            download_bytes=_integer(row["download_bytes"]),
            deducted_bytes=_integer(row["deducted_bytes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InfluxDB3Error(
            "InfluxDB 3 returned an invalid subscription_traffic_daily row"
        ) from exc


def daily_final_time(usage_date: date) -> datetime:
    """Return the local final timestamp used for historical daily points."""
    return datetime.combine(usage_date, time(23, 59, 59)).astimezone()


def _tag(value: str) -> str:
    _validate_line_value(value)
    return value.replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def _field_string(value: str) -> str:
    _validate_line_value(value)
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _validate_line_value(value: str) -> None:
    if "\n" in value or "\r" in value:
        raise ValueError("InfluxDB 3 line protocol values must not contain line breaks")


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer field")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdecimal():
        result = int(value)
    else:
        raise ValueError("invalid integer field")
    if result < 0:
        raise ValueError("negative integer field")
    return result


def _string(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid string field")
    return value


class InfluxDB3SubscriptionTrafficWriter:
    """Append current observations; preserve immutable historical final points."""

    def __init__(self, client: InfluxDB3Client) -> None:
        self._client = client

    def write(self, snapshot: SubscriptionTrafficSnapshot) -> int:
        """Write pending current and historical traffic observations."""
        if not snapshot.usages:
            return 0
        table_exists = self._table_exists()
        pending = [
            usage
            for usage in snapshot.usages
            if self._should_write(usage, snapshot.today, table_exists)
        ]
        self._client.write_lines(
            [encode_subscription_traffic_usage(usage, snapshot.observed_at) for usage in pending]
        )
        return len(pending)

    def _should_write(
        self, usage: SubscriptionTrafficUsage, today: date, table_exists: bool
    ) -> bool:
        if usage.usage_date == today or not table_exists:
            return True
        existing = self._existing_final(usage)
        if existing is None:
            return True
        if existing != usage:
            raise InfluxDB3Error(
                "InfluxDB 3 already contains a different daily final for "
                f"provider={usage.provider}, user_id={usage.user_id}, "
                f"usage_date={usage.usage_date.isoformat()}"
            )
        return False

    def _table_exists(self) -> bool:
        return bool(
            self._client.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'iox' AND table_name = $table_name",
                {"table_name": _SUBSCRIPTION_TRAFFIC_TABLE},
            )
        )

    def _existing_final(
        self, expected: SubscriptionTrafficUsage
    ) -> SubscriptionTrafficUsage | None:
        # Intraday snapshots from yesterday are not immutable historical finals.
        final_time = daily_final_time(expected.usage_date).astimezone(UTC)
        rows = self._client.query(
            "SELECT upload_bytes, download_bytes, deducted_bytes, server_rate, usage_date "
            f'FROM "{_SUBSCRIPTION_TRAFFIC_TABLE}" '
            "WHERE provider = $provider AND user_id = $user_id "
            "AND usage_date = $usage_date AND time = CAST($final_time AS TIMESTAMP) LIMIT 2",
            {
                "provider": expected.provider,
                "user_id": expected.user_id,
                "usage_date": expected.usage_date.isoformat(),
                "final_time": final_time.isoformat(),
            },
        )
        if not rows:
            return None
        if len(rows) > 1:
            raise InfluxDB3Error("InfluxDB 3 contains multiple daily final points")
        return decode_subscription_traffic_usage(rows[0], expected)
