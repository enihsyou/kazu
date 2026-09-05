from __future__ import annotations

from datetime import date, datetime, time

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


class InfluxDB3SubscriptionTrafficWriter:
    """Append current observations; preserve immutable historical final points."""

    def __init__(self, client: InfluxDB3Client) -> None:
        self._client = client
        self._historical_finals: dict[tuple[str, str, date], SubscriptionTrafficUsage] = {}

    def table_exists(self) -> bool:
        """Check once at startup whether the target measurement already exists."""
        return bool(
            self._client.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'iox' AND table_name = $table_name",
                {"table_name": _SUBSCRIPTION_TRAFFIC_TABLE},
            )
        )

    def write(self, snapshot: SubscriptionTrafficSnapshot) -> int:
        """Write pending current and historical traffic observations."""
        if not snapshot.usages:
            return 0
        pending, pending_finals = self._pending(snapshot)
        self._client.write_lines(
            [encode_subscription_traffic_usage(usage, snapshot.observed_at) for usage in pending]
        )
        self._historical_finals.update(pending_finals)
        return len(pending)

    def _pending(
        self, snapshot: SubscriptionTrafficSnapshot
    ) -> tuple[
        list[SubscriptionTrafficUsage],
        dict[tuple[str, str, date], SubscriptionTrafficUsage],
    ]:
        pending: list[SubscriptionTrafficUsage] = []
        pending_finals: dict[tuple[str, str, date], SubscriptionTrafficUsage] = {}
        for usage in snapshot.usages:
            if usage.usage_date == snapshot.today:
                pending.append(usage)
                continue
            key = (usage.provider, usage.user_id, usage.usage_date)
            existing = pending_finals.get(key, self._historical_finals.get(key))
            if existing is None:
                pending.append(usage)
                pending_finals[key] = usage
            elif existing != usage:
                raise InfluxDB3Error(
                    "A different historical daily final was already observed for "
                    f"provider={usage.provider}, user_id={usage.user_id}, "
                    f"usage_date={usage.usage_date.isoformat()}"
                )
        return pending, pending_finals
