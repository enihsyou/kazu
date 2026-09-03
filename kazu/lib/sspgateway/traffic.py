"""Parse SSP traffic responses and validate their scalar values."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from kazu.lib.sspgateway.models import APIResult, TrafficLogResult, TrafficRecord


def parse_traffic_log(result: APIResult) -> TrafficLogResult:
    """Parse a raw API result into validated traffic records."""
    records = tuple(_parse_record(item) for item in _traffic_items(result.data))
    return TrafficLogResult(
        endpoint=result.endpoint,
        status_code=result.status_code,
        records=records,
        data=result.data,
        message=result.message,
        raw=result.raw,
    )


def _traffic_items(data: Any) -> list[Mapping[str, Any]]:
    candidates = data
    if isinstance(candidates, Mapping):
        for key in ("data", "records"):
            value = candidates.get(key)
            if isinstance(value, list):
                candidates = value
                break
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, Mapping)]


def _parse_record(item: Mapping[str, Any]) -> TrafficRecord:
    return TrafficRecord(
        user_id=_identifier(item.get("user_id")),
        recorded_at=_datetime(item.get("record_at")),
        upload_bytes=_integer(item.get("u")),
        download_bytes=_integer(item.get("d")),
        multiplier=_decimal(item.get("server_rate")),
        raw=dict(item),
    )


def _identifier(value: Any) -> int | str:
    if isinstance(value, bool):
        raise ValueError("SSP traffic record has an invalid user_id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError("SSP traffic record is missing user_id")


def _datetime(value: Any) -> datetime:
    if isinstance(value, int | float) and not isinstance(value, bool):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            raise ValueError("SSP traffic record has an invalid record_at") from None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("SSP traffic record has an invalid record_at") from None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    raise ValueError("SSP traffic record is missing record_at")


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("SSP traffic record has an invalid traffic value")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    raise ValueError("SSP traffic record has an invalid traffic value")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("SSP traffic record is missing server_rate")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("SSP traffic record has an invalid server_rate") from None
    if not result.is_finite():
        raise ValueError("SSP traffic record has an invalid server_rate")
    return result
