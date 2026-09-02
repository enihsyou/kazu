from __future__ import annotations

# ruff: noqa: E501 -- the fixed encrypted bootstrap setting must remain byte-exact.
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Self
from urllib.parse import unquote, urlencode, urljoin, urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BOOTSTRAP_MASTER_KEY = "218f1c43e24751dfeaa1a78e3643d84b"
SECURE_SETTING = "SC0IMUV8a3XGjNONp76L5pH7uwVmI1Ss0KomKd16B1K1aS6aldz5woo0yDST37m6mMR9Evch24J7JMesQJNglKZpYNG9n+iI1XtI2C1qSWkLAqZs9GLJgm01wP0zwXWIqyY/rILf8I/CNBemYFVZb1xc4Ua+ccmYZy+R5T3RMdL4e2/B152qhIcjHrI1GwAoHBGgW7xx1YRmJeyqbY8j2uwjLoeRw6a8n0oC52ZXAmsJA6pevzOXl30y2rBxzWeEvWU7g4ie8Ymdf0DjLFpDZyJfoQK4LteYYyfA8nKGZYmvZjOdvZ/2kNVxH7EyAB49UxbwU+IygsE/IIW5LoU2hfkpbMTYhanX1S8fszQJTj9GXqlAvmSY3Sol1qx8kWiQuiI1ncOKvqn1RmGka0oMSBsEt1WpIpjdKiiC53HBO7vsMTLeov6+zJJzQ6lXag4mXBqiHZFTmN0qN9rySa0jzOwgNd6q4r7MkmxFqVZuDiZcFqIdklGYrCRj37B4jCPaoD42n82S+4HEc1rle2ZJZBoArFm1d8nTMmPbq2uTctqSZAbcmYGylNhzTutwXF8kCh+zHLN3zoF7e+/wQ8x5za0kKJbM2+6F33tJ4mVUWSQdHu5Ds2LUlmAg2vF5gGCQvmUoho+SsMLCeVjwZ2ZKZh8X4Qr5ZdaQbwCR8z2OYJO6LiisitXlv9IgGfFwVQ4wXCqcSoFg1cNHc9qPfJJloasZK7mk8dqEwWx79UloQn08Ce4IqVL4uWEJhes9ng=="

DEFAULT_API_BASE_URL = "https://s1.thefew01.top/api/v1"
DEFAULT_GATEWAY_ENDPOINTS = ("https://x1.thecores.top/",)
DEFAULT_TRAFFIC_ENDPOINT = "user/stat/getTrafficLog"
_TRAFFIC_PATH_SUFFIX = "/user/stat/getTrafficLog"
# The live client passes Authorization as an outer gateway header.  Only the
# lower-case x-api-key spelling is moved into the encrypted canonical payload.
_PROTECTED_HEADERS = frozenset({"x-api-key"})
_BEARER_AUTH_RE = re.compile(r"^Bearer ([^\s]+)$", re.IGNORECASE)
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


class SSPGatewayError(RuntimeError):
    """Base error for gateway configuration, transport, and protocol failures."""


class GatewayNetworkError(SSPGatewayError):
    """All configured gateways failed at the transport layer."""


class GatewayProtocolError(SSPGatewayError):
    """The gateway response could not be authenticated or decoded."""


class GatewayHTTPError(SSPGatewayError):
    def __init__(self, status_code: int, message: str, result: APIResult | None = None) -> None:
        super().__init__(f"SSP API returned HTTP {status_code}: {message}")
        self.status_code = status_code
        self.result = result


@dataclass(frozen=True)
class GatewayTrace:
    request_http: str
    response_http: str


@dataclass(frozen=True)
class GatewayResponse:
    status_code: int
    reason_phrase: str
    content_type: str
    content: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayProtocolError("Decrypted SSP response is not valid JSON") from exc


@dataclass(frozen=True)
class APIResult:
    endpoint: str
    status_code: int
    data: Any
    message: str | None
    raw: Any


@dataclass(frozen=True)
class TrafficRecord:
    user_id: int | str
    recorded_at: datetime
    upload_bytes: int
    download_bytes: int
    multiplier: Decimal
    raw: Mapping[str, Any]

    @property
    def total_bytes(self) -> int:
        return self.upload_bytes + self.download_bytes

    @property
    def billed_bytes(self) -> Decimal:
        return Decimal(self.total_bytes) * self.multiplier


@dataclass(frozen=True)
class TrafficLogResult:
    endpoint: str
    status_code: int
    records: tuple[TrafficRecord, ...]
    data: Any
    message: str | None
    raw: Any


TraceCallback = Callable[[GatewayTrace], None]


class SSPGateway:
    """Client for the stable, read-only SSP API surface routed through its encrypted gateway."""

    def __init__(
        self,
        authorization: str,
        *,
        api_base_url: str = DEFAULT_API_BASE_URL,
        traffic_endpoint: str = DEFAULT_TRAFFIC_ENDPOINT,
        gateway_endpoints: Sequence[str] = DEFAULT_GATEWAY_ENDPOINTS,
        timeout: float = 15.0,
        trace: TraceCallback | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self._authorization = _normalize_authorization(authorization)
        self.api_base_url = _validate_api_base_url(api_base_url)
        self.traffic_endpoint = _validate_traffic_endpoint(traffic_endpoint)
        self.gateway_endpoints = _validate_gateway_endpoints(gateway_endpoints)
        self.timeout = float(timeout)
        self.trace = trace

        bootstrap = _bootstrap_config()
        master_key = _b64url_decode(_required_string(bootstrap, "master_key_b64url"))
        if len(master_key) != 32:
            raise GatewayProtocolError("Bootstrap gateway master key must be 32 bytes")
        self._route_flag = _optional_string(bootstrap, "route_flag")
        self._enc_key, self._mac_key = _derive_session_keys(master_key)
        self._client = httpx.Client(timeout=self.timeout, follow_redirects=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def call_get_user_info(self) -> APIResult:
        return self._get_json("user/info")

    def call_get_user_stat(self) -> APIResult:
        return self._get_json("user/getStat")

    def call_get_subscription(self) -> APIResult:
        return self._get_json("user/getSubscribe")

    def call_fetch_orders(self) -> APIResult:
        return self._get_json("user/order/fetch")

    def call_get_order_detail(self, trade_no: str) -> APIResult:
        if not trade_no.strip():
            raise ValueError("trade_no must not be empty")
        query = urlencode({"trade_no": trade_no.strip()})
        return self._get_json(f"user/order/detail?{query}")

    def get_traffic_log(self) -> TrafficLogResult:
        result = self._get_json(self.traffic_endpoint)
        records = tuple(_parse_traffic_record(item) for item in _traffic_items(result.data))
        return TrafficLogResult(
            endpoint=result.endpoint,
            status_code=result.status_code,
            records=records,
            data=result.data,
            message=result.message,
            raw=result.raw,
        )

    def _get_json(self, endpoint: str) -> APIResult:
        response = self._request_get(endpoint)
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

    def _request_get(self, endpoint: str) -> GatewayResponse:
        api_url = _resolve_api_url(self.api_base_url, endpoint)
        canonical, original_headers = self._canonical_get(api_url)
        canonical_bytes = json.dumps(
            canonical,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        timestamp = int(time.time() * 1000)
        nonce = os.urandom(16)
        encrypted = AESGCM(self._enc_key).encrypt(
            nonce[:12],
            canonical_bytes,
            timestamp.to_bytes(8, "big") + nonce,
        )
        ciphertext, tag = encrypted[:-16], encrypted[-16:]
        signature = hmac.new(
            self._mac_key,
            timestamp.to_bytes(8, "big") + nonce + canonical_bytes,
            hashlib.sha256,
        ).digest()
        body = {"ciphertext": _b64url_encode(ciphertext), "tag": _b64url_encode(tag)}
        headers = _gateway_headers(
            original_headers,
            nonce=nonce,
            timestamp=timestamp,
            signature=signature,
            route_flag=self._route_flag,
        )
        return self._send_gateway(api_url, headers, body)

    def _canonical_get(self, api_url: str) -> tuple[dict[str, Any], dict[str, str]]:
        original_headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Language": "zh-CN",
            "Authorization": self._authorization,
        }
        lowered = {name.lower(): value.strip() for name, value in original_headers.items()}
        protected = {
            name: lowered[name] for name in sorted(_PROTECTED_HEADERS) if lowered.get(name)
        }
        parsed = urlsplit(api_url)
        canonical = {
            "method": "GET",
            "path": _normalize_path(parsed.path),
            "query": _normalize_query(parsed.query),
            "headers": protected,
            "body": "",
        }
        return canonical, original_headers

    def _send_gateway(
        self,
        api_url: str,
        headers: Mapping[str, str],
        body: Mapping[str, str],
    ) -> GatewayResponse:
        last_error: httpx.TransportError | None = None
        for endpoint in self.gateway_endpoints:
            try:
                response = self._client.post(endpoint, headers=headers, json=body)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            request_trace = _request_trace(endpoint, headers, body)
            return self._decrypt_gateway_response(response, request_trace)
        raise GatewayNetworkError("All configured gateway endpoints failed") from last_error

    def _decrypt_gateway_response(
        self,
        response: httpx.Response,
        request_trace: str,
    ) -> GatewayResponse:
        mode = response.headers.get("X-Response-Encrypted")
        if mode != "AES-GCM":
            raise GatewayProtocolError(f"Expected encrypted gateway response, received {mode!r}")
        nonce_header = response.headers.get("X-Response-Nonce")
        if not nonce_header:
            raise GatewayProtocolError("Encrypted gateway response is missing its nonce")
        try:
            envelope = response.json()
            ciphertext = _b64url_decode(_required_string(envelope, "ciphertext"))
            tag = _b64url_decode(_required_string(envelope, "tag"))
            nonce = _b64url_decode(nonce_header)
            plaintext = AESGCM(self._enc_key).decrypt(nonce[:12], ciphertext + tag, None)
        except (
            ValueError,
            KeyError,
            TypeError,
            binascii.Error,
            InvalidTag,
            json.JSONDecodeError,
        ) as exc:
            raise GatewayProtocolError("Unable to decrypt gateway response") from exc

        content_type = _optional_string(envelope, "contentType") or "application/octet-stream"
        result = GatewayResponse(
            status_code=response.status_code,
            reason_phrase=response.reason_phrase,
            content_type=content_type,
            content=plaintext,
        )
        if self.trace is not None:
            self.trace(GatewayTrace(request_trace, _response_trace(response, result)))
        return result


def _validate_api_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("api_base_url must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("api_base_url must not contain a query or fragment")
    return value.rstrip("/")


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


def _validate_traffic_endpoint(value: str) -> str:
    endpoint = value.strip()
    parsed = urlsplit(endpoint)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.query:
        raise ValueError("traffic_endpoint must be a relative path without query parameters")
    normalized = "/" + endpoint.lstrip("/")
    if not normalized.endswith(_TRAFFIC_PATH_SUFFIX):
        raise ValueError("traffic_endpoint must end with user/stat/getTrafficLog")
    return endpoint.lstrip("/")


def _validate_gateway_endpoints(values: Sequence[str]) -> tuple[str, ...]:
    endpoints = tuple(value.strip() for value in values if value.strip())
    if not endpoints:
        raise ValueError("At least one gateway endpoint is required")
    for endpoint in endpoints:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("gateway endpoints must be absolute HTTP(S) URLs")
    return endpoints


def _resolve_api_url(base_url: str, endpoint: str) -> str:
    return urljoin(f"{base_url}/", endpoint.lstrip("/"))


def _normalize_path(path: str) -> str:
    try:
        decoded = unquote(path, errors="strict")
    except UnicodeDecodeError:
        decoded = path
    normalized = re.sub(r"/+", "/", decoded)
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _normalize_query(query: str) -> str:
    return "&".join(part if "=" in part else f"{part}=" for part in query.split("&") if part)


def _gateway_headers(
    original: Mapping[str, str],
    *,
    nonce: bytes,
    timestamp: int,
    signature: bytes,
    route_flag: str,
) -> dict[str, str]:
    headers = {
        name: value for name, value in original.items() if name.lower() not in _PROTECTED_HEADERS
    }
    headers.update(
        {
            "Content-Type": "application/json",
            "X-Cipher-Mode": "AES-GCM",
            "X-Nonce": _b64url_encode(nonce),
            "X-Timestamp": str(timestamp),
            "X-Signature": _b64url_encode(signature),
            "X-Gateway-Flag": route_flag,
        }
    )
    return headers


def _derive_session_keys(master_key: bytes) -> tuple[bytes, bytes]:
    prk = hmac.new(bytes(32), master_key, hashlib.sha256).digest()
    enc_key = hmac.new(prk, b"secure-gateway-enc\x01", hashlib.sha256).digest()
    mac_key = hmac.new(prk, b"secure-gateway-mac\x01", hashlib.sha256).digest()
    return enc_key, mac_key


@lru_cache(maxsize=1)
def _bootstrap_config() -> Mapping[str, Any]:
    try:
        payload = base64.b64decode(SECURE_SETTING, validate=True)
    except ValueError as exc:
        raise GatewayProtocolError("Built-in SSP bootstrap setting is invalid") from exc
    if len(payload) < 33:
        raise GatewayProtocolError("Built-in SSP bootstrap setting is truncated")
    key_hash = hashlib.sha256(BOOTSTRAP_MASTER_KEY.encode()).digest()
    provided_mac, body = payload[:32], payload[32:]
    expected_mac = hmac.new(key_hash, body, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_mac, expected_mac):
        raise GatewayProtocolError("Built-in SSP bootstrap setting failed authentication")
    plaintext = bytes(value ^ key_hash[index % len(key_hash)] for index, value in enumerate(body))
    try:
        config = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayProtocolError("Built-in SSP bootstrap setting is not valid JSON") from exc
    if not isinstance(config, Mapping):
        raise GatewayProtocolError("Built-in SSP bootstrap setting has an invalid shape")
    return config


def _required_string(value: Any, key: str) -> str:
    if not isinstance(value, Mapping):
        raise GatewayProtocolError("Gateway envelope has an invalid shape")
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise GatewayProtocolError(f"Gateway envelope is missing {key}")
    return item


def _optional_string(value: Any, key: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    item = value.get(key)
    return item if isinstance(item, str) else ""


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _unwrap_api_payload(raw: Any) -> tuple[Any, str | None]:
    if not isinstance(raw, Mapping):
        return raw, None
    data = raw.get("data", raw)
    message = raw.get("message")
    return data, message if isinstance(message, str) else None


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


def _parse_traffic_record(item: Mapping[str, Any]) -> TrafficRecord:
    return TrafficRecord(
        user_id=_as_identifier(item.get("user_id")),
        recorded_at=_as_datetime(item.get("record_at")),
        upload_bytes=_as_int(item.get("u")),
        download_bytes=_as_int(item.get("d")),
        multiplier=_as_decimal(item.get("server_rate")),
        raw=dict(item),
    )


def _as_identifier(value: Any) -> int | str:
    if isinstance(value, bool):
        raise ValueError("SSP traffic record has an invalid user_id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError("SSP traffic record is missing user_id")


def _as_datetime(value: Any) -> datetime:
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


def _as_int(value: Any) -> int:
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


def _as_decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("SSP traffic record is missing server_rate")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("SSP traffic record has an invalid server_rate") from None
    if not result.is_finite():
        raise ValueError("SSP traffic record has an invalid server_rate")
    return result


def _request_trace(
    gateway_url: str,
    headers: Mapping[str, str],
    body: Mapping[str, str],
) -> str:
    parsed = urlsplit(gateway_url)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    redacted_body = {key: "<redacted>" for key in body}
    lines = [f"POST {target} HTTP/1.1", f"Host: {parsed.netloc}"]
    lines.extend(_redacted_header_lines(headers))
    lines.extend(("", json.dumps(redacted_body, separators=(",", ":"))))
    return "\n".join(lines)


def _response_trace(response: httpx.Response, decrypted: GatewayResponse) -> str:
    version = response.http_version.removeprefix("HTTP/")
    lines = [f"HTTP/{version} {response.status_code} {response.reason_phrase}"]
    lines.append(f"Content-Type: {decrypted.content_type}")
    lines.extend(_redacted_header_lines(response.headers))
    lines.extend(("", _redacted_body(decrypted.content)))
    return "\n".join(lines)


def _redacted_header_lines(headers: Mapping[str, str]) -> list[str]:
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
