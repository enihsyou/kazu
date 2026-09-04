from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, Self
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from kazu.lib.sspgateway.codec import GatewayCodec
from kazu.lib.sspgateway.errors import GatewayHTTPError, GatewayNetworkError
from kazu.lib.sspgateway.models import (
    APIResult,
    GatewayResponse,
    GatewayTrace,
    TraceCallback,
    TrafficLogResult,
)
from kazu.lib.sspgateway.trace import format_request_trace, format_response_trace
from kazu.lib.sspgateway.traffic import parse_traffic_log

DEFAULT_API_BASE_URL = "https://s1.thefew01.top/api/v1"
"""Provide the default SSP API base URL."""

DEFAULT_GATEWAY_BASE_URL = "https://x1.thecores.top"
"""Provide the default encrypted gateway base URL."""

DEFAULT_TRAFFIC_ENDPOINT = "user/stat/getTrafficLog"
"""Provide the default read-only traffic endpoint."""
_BEARER_AUTH_RE = re.compile(r"^Bearer ([^\s]+)$", re.IGNORECASE)


class SSPGateway:
    """The stable, read-only SSP API surface, routed through its encrypted gateway."""

    def __init__(
        self,
        authorization: str,
        *,
        api_base_url: str = DEFAULT_API_BASE_URL,
        gateway_base_url: str = DEFAULT_GATEWAY_BASE_URL,
        timeout: float = 15.0,
        trace: TraceCallback | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.api_base_url = _validate_api_base_url(api_base_url)
        """Store the validated SSP API base URL."""

        self.gateway_base_url = _validate_gateway_base_url(gateway_base_url)
        """Store the validated encrypted gateway base URL."""

        self.timeout = float(timeout)
        """Store the HTTP request timeout in seconds."""

        self.trace = trace
        """Store the optional redacted exchange trace callback."""

        self._codec = GatewayCodec(_normalize_authorization(authorization))
        self._client = httpx.Client(timeout=self.timeout, follow_redirects=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def call_get_user_info(self) -> APIResult:
        """Fetch the authenticated user's raw profile result."""
        return self._get_json("user/info")

    def call_get_user_stat(self) -> APIResult:
        """Fetch the authenticated user's raw traffic statistics result."""
        return self._get_json("user/getStat")

    def call_get_subscription(self) -> APIResult:
        """Fetch the authenticated user's raw subscription result."""
        return self._get_json("user/getSubscribe")

    def call_fetch_orders(self) -> APIResult:
        """Fetch the authenticated user's raw order list result."""
        return self._get_json("user/order/fetch")

    def call_get_order_detail(self, trade_no: str) -> APIResult:
        """Fetch one raw order detail result by trade number."""
        if not trade_no.strip():
            raise ValueError("trade_no must not be empty")
        query = urlencode({"trade_no": trade_no.strip()})
        return self._get_json(f"user/order/detail?{query}")

    def get_traffic_log(self) -> TrafficLogResult:
        """Fetch and parse the authenticated user's traffic log."""
        return parse_traffic_log(self._get_json(DEFAULT_TRAFFIC_ENDPOINT))

    def _get_json(self, endpoint: str) -> APIResult:
        api_url = urljoin(f"{self.api_base_url}/", endpoint.lstrip("/"))
        headers, body = self._codec.encode_get(api_url)
        response = self._send_gateway(headers, body)
        raw = response.json()
        data, message = _unwrap_api_payload(raw)
        result = APIResult(
            endpoint=endpoint,
            status_code=response.status_code,
            data=data,
            message=message,
            raw=raw,
        )
        if response.status_code >= 400:
            raise GatewayHTTPError(response.status_code, message or response.reason_phrase, result)
        return result

    def _send_gateway(
        self,
        headers: Mapping[str, str],
        body: Mapping[str, str],
    ) -> GatewayResponse:
        try:
            response = self._client.post(self.gateway_base_url, headers=headers, json=body)
        except httpx.TransportError as exc:
            raise GatewayNetworkError("Gateway request failed") from exc
        result = self._codec.decode_response(response)
        if self.trace is not None:
            self.trace(
                GatewayTrace(
                    format_request_trace(self.gateway_base_url, headers, body),
                    format_response_trace(response, result),
                )
            )
        return result


def _validate_api_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("api_base_url must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("api_base_url must not contain a query or fragment")
    return value.strip().rstrip("/")


def _normalize_authorization(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Authorization must be a string")
    authorization = value.strip()
    match = _BEARER_AUTH_RE.fullmatch(authorization)
    if match is None:
        raise ValueError(
            "Authorization must be a complete Bearer scheme and a non-empty credential "
            "without whitespace"
        )
    return f"Bearer {match.group(1)}"


def _validate_gateway_base_url(value: str) -> str:
    base_url = value.strip()
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("gateway_base_url must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("gateway_base_url must not contain a query or fragment")
    return base_url.rstrip("/")


def _unwrap_api_payload(raw: Any) -> tuple[Any, str | None]:
    if not isinstance(raw, Mapping):
        return raw, None
    data = raw.get("data", raw)
    message = raw.get("message")
    return data, message if isinstance(message, str) else None
