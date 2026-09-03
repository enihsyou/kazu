from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from kazu.lib.sspgateway.errors import GatewayProtocolError


@dataclass(frozen=True)
class GatewayTrace:
    """Contain redacted HTTP transcripts for one gateway exchange."""

    request_http: str
    """Store the redacted outbound request transcript."""

    response_http: str
    """Store the redacted inbound response transcript."""


@dataclass(frozen=True)
class GatewayResponse:
    """Represent a decrypted gateway HTTP response."""

    status_code: int
    """Store the HTTP status code."""

    reason_phrase: str
    """Store the HTTP reason phrase."""

    content_type: str
    """Store the decrypted response content type."""

    content: bytes
    """Store the decrypted response body."""

    def json(self) -> Any:
        """Decode the decrypted response body as JSON."""
        try:
            return json.loads(self.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayProtocolError("Decrypted SSP response is not valid JSON") from exc


@dataclass(frozen=True)
class APIResult:
    """Represent one raw SSP API result before endpoint-specific parsing."""

    endpoint: str
    """Store the API endpoint that produced the result."""

    status_code: int
    """Store the HTTP status code returned by the API."""

    data: Any
    """Store the unwrapped API data payload."""

    message: str | None
    """Store the optional API response message."""

    raw: Any
    """Store the complete raw API response payload."""


@dataclass(frozen=True)
class TrafficRecord:
    """Represent one parsed SSP traffic log record."""

    user_id: int | str
    """Store the stable user identifier from the traffic record."""

    recorded_at: datetime
    """Store the exact timestamp reported for the record."""

    upload_bytes: int
    """Store the uploaded byte count."""

    download_bytes: int
    """Store the downloaded byte count."""

    multiplier: Decimal
    """Store the billing multiplier used by the provider."""

    raw: Mapping[str, Any]
    """Store the original traffic record fields."""

    @property
    def total_bytes(self) -> int:
        """Return the combined uploaded and downloaded byte count."""
        return self.upload_bytes + self.download_bytes

    @property
    def billed_bytes(self) -> Decimal:
        """Return the traffic count after applying the billing multiplier."""
        return Decimal(self.total_bytes) * self.multiplier


@dataclass(frozen=True)
class TrafficLogResult:
    """Represent a parsed SSP traffic log response."""

    endpoint: str
    """Store the API endpoint that produced the log."""

    status_code: int
    """Store the HTTP status code returned by the API."""

    records: tuple[TrafficRecord, ...]
    """Store the parsed traffic records."""

    data: Any
    """Store the unwrapped API data payload."""

    message: str | None
    """Store the optional API response message."""

    raw: Any
    """Store the complete raw API response payload."""


TraceCallback = Callable[[GatewayTrace], None]
"""Describe callbacks that receive redacted gateway traces."""
