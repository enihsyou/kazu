"""Redact configured credentials from diagnostics and log messages."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

_SECRET_NAMES = (
    "apikey",
    "accesskey",
    "servicekey",
    "privatekey",
    "token",
    "secret",
    "password",
    "cookie",
    "authorization",
)
_REGISTERED_SECRETS: set[str] = set()


def _secret_values(values: Mapping[str, str | None]) -> set[str]:
    secrets = set()
    for name, value in values.items():
        normalized = name.lower().replace("_", "").replace("-", "")
        if not value or not any(part in normalized for part in _SECRET_NAMES):
            continue
        secrets.add(value)
        if "authorization" in normalized:
            scheme, separator, credential = value.strip().partition(" ")
            if separator and scheme.lower() in {"bearer", "basic"} and credential.strip():
                secrets.add(credential.strip())
        if "cookie" in normalized:
            for cookie in value.split(";"):
                _, separator, credential = cookie.partition("=")
                credential = credential.strip().strip('"')
                if separator and credential:
                    secrets.add(credential)
    return secrets


def register_secrets(values: Mapping[str, str | None]) -> None:
    """Remember credentials read from .env or other configuration sources."""
    _REGISTERED_SECRETS.update(_secret_values(values))


def redact(text: str, values: Mapping[str, str | None] | None = None) -> str:
    """Hide known secrets, including when they appear without a field name."""
    secrets = _REGISTERED_SECRETS | _secret_values(os.environ)
    if values is not None:
        secrets.update(_secret_values(values))
    # Replace the complete credential before any token or cookie contained in it.
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True
