"""Format redacted HTTP transcripts independently of terminal rendering."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from kazu.lib.sspgateway.models import GatewayResponse

_TRACE_SECRET_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-gateway-flag",
        "x-nonce",
        "x-response-nonce",
        "x-signature",
        "x-timestamp",
    }
)
_JSON_SECRET_FRAGMENTS = (
    "authorization",
    "callback_no",
    "cookie",
    "password",
    "secret",
    "signature",
    "subscribe_url",
    "token",
    "trade_no",
    "uuid",
)


def format_request_trace(
    gateway_url: str,
    headers: Mapping[str, str],
    body: Mapping[str, str],
) -> str:
    """Format a redacted outbound gateway request transcript."""
    parsed = urlsplit(gateway_url)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    redacted_body = {key: "<redacted>" for key in body}
    lines = [f"POST {target} HTTP/1.1", f"Host: {parsed.netloc}"]
    lines.extend(_header_lines(headers))
    lines.extend(("", json.dumps(redacted_body, separators=(",", ":"))))
    return "\n".join(lines)


def format_response_trace(response: httpx.Response, decrypted: GatewayResponse) -> str:
    """Format a redacted inbound gateway response transcript."""
    version = response.http_version.removeprefix("HTTP/")
    lines = [f"HTTP/{version} {response.status_code} {response.reason_phrase}"]
    lines.append(f"Content-Type: {decrypted.content_type}")
    lines.extend(_header_lines(response.headers))
    lines.extend(("", _redacted_body(decrypted.content)))
    return "\n".join(lines)


def _header_lines(headers: Mapping[str, str]) -> list[str]:
    lines: list[str] = []
    for name, value in headers.items():
        shown = "<redacted>" if name.lower() in _TRACE_SECRET_KEYS else value
        lines.append(f"{name}: {shown}")
    return lines


def _redacted_body(content: bytes) -> str:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"<binary body: {len(content)} bytes>"
    return json.dumps(_redact_json(value), ensure_ascii=False, indent=2)


def _redact_json(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            sensitive = any(fragment in normalized for fragment in _JSON_SECRET_FRAGMENTS)
            redacted[str(key)] = "<redacted>" if sensitive else _redact_json(item)
        return redacted
    return value
