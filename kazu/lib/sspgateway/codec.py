from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kazu.lib.sspgateway.bootstrap import load_bootstrap
from kazu.lib.sspgateway.errors import GatewayProtocolError
from kazu.lib.sspgateway.models import GatewayResponse

# Authorization remains an outer gateway header, as in the live SSP client.
_PROTECTED_HEADERS = frozenset({"x-api-key"})


class GatewayCodec:
    """Canonicalization, authenticated request encryption, and response decryption."""

    def __init__(self, authorization: str) -> None:
        self._authorization = authorization
        bootstrap = load_bootstrap()
        master_key = _b64url_decode(_required_string(bootstrap, "master_key_b64url"))
        if len(master_key) != 32:
            raise GatewayProtocolError("Bootstrap gateway master key must be 32 bytes")
        self._route_flag = _optional_string(bootstrap, "route_flag")
        self._enc_key, self._mac_key = _derive_session_keys(master_key)

    def encode_get(self, api_url: str) -> tuple[dict[str, str], dict[str, str]]:
        """Encrypt and authenticate a read-only GET request envelope."""
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
        body = {
            "ciphertext": _b64url_encode(ciphertext),
            "tag": _b64url_encode(tag),
        }
        headers = _gateway_headers(
            original_headers,
            nonce=nonce,
            timestamp=timestamp,
            signature=signature,
            route_flag=self._route_flag,
        )
        return headers, body

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

    def decode_response(
        self,
        response: httpx.Response,
    ) -> GatewayResponse:
        """Authenticate and decrypt an encrypted gateway response."""
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
        return result


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
