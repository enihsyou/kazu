"""Read provider JSON without exposing response bodies or credentials in errors."""

from __future__ import annotations

from typing import Any

import httpx

from kazu.lib.redaction import redact
from kazu.lib.usage import CollectionError


def get_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    params: dict[str, str | int] | None = None,
) -> dict[str, Any]:
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, params=params)
    except httpx.RequestError as exc:
        detail = str(exc).strip() or f"request timeout={timeout}s"
        detail = redact(detail, headers)
        raise CollectionError(f"API request failed ({type(exc).__name__}): {detail}") from None
    if not response.is_success:
        raise CollectionError(f"API query failed (HTTP {response.status_code})")
    try:
        data = response.json()
    except ValueError:
        raise CollectionError("API did not return valid JSON") from None
    if not isinstance(data, dict):
        raise CollectionError("API did not return a JSON object")
    return data
