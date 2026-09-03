from __future__ import annotations

import math
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from kazu.config import InfluxDB3Config


class InfluxDB3Error(RuntimeError):
    """InfluxDB 3 configuration, query, or write failure."""


class InfluxDB3Client:
    """Small HTTP client; errors never include the token or response body."""

    def __init__(self, config: InfluxDB3Config) -> None:
        _validate_config(config)
        self._database = config.database.strip()
        self._base_url = config.host.strip().rstrip("/")
        try:
            self._client = httpx.Client(
                timeout=config.timeout,
                headers={"Authorization": f"Bearer {config.token.strip()}"},
                follow_redirects=False,
            )
        except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError) as exc:
            raise InfluxDB3Error(
                f"Unable to initialize the InfluxDB 3 client ({type(exc).__name__})"
            ) from exc

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying InfluxDB HTTP client."""
        self._client.close()

    def check_connection(self) -> None:
        """Check database/query authorization without inserting a probe point."""
        rows = self.query("SELECT 1 AS ready")
        if len(rows) != 1 or type(rows[0].get("ready")) is not int or rows[0]["ready"] != 1:
            raise InfluxDB3Error("InfluxDB 3 database check returned an unexpected response")

    def query(self, query: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return its JSON rows."""
        response = self._post(
            "/api/v3/query_sql",
            json={
                "db": self._database,
                "q": query,
                "params": params or {},
                "format": "json",
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise InfluxDB3Error("InfluxDB 3 query returned invalid JSON") from exc
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise InfluxDB3Error("InfluxDB 3 query returned an unexpected response")
        return payload

    def write_lines(self, lines: list[str]) -> None:
        """Write line-protocol records to InfluxDB."""
        if not lines:
            return
        self._post(
            "/api/v3/write_lp",
            params={"db": self._database, "precision": "ns", "accept_partial": "false"},
            content="\n".join(lines),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )

    def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.post(f"{self._base_url}{path}", **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InfluxDB3Error(
                f"InfluxDB 3 {path} failed: HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError) as exc:
            raise InfluxDB3Error(
                f"InfluxDB 3 {path} request failed ({type(exc).__name__})"
            ) from exc
        return response


def _validate_config(config: InfluxDB3Config) -> None:
    missing = [
        name
        for name, value in (
            ("host", config.host),
            ("database", config.database),
            ("token", config.token),
        )
        if not value.strip()
    ]
    if missing:
        names = ", ".join(f"influxdb3.{name}" for name in missing)
        raise InfluxDB3Error(f"InfluxDB 3 configuration is incomplete: {names}")
    try:
        host = urlsplit(config.host.strip())
        valid_host = (
            host.scheme in {"http", "https"}
            and host.hostname
            and not host.username
            and not host.password
            and not host.query
            and not host.fragment
            and host.port != 0
        )
    except ValueError:
        valid_host = False
    if not valid_host:
        raise InfluxDB3Error("influxdb3.host must be an absolute HTTP(S) URL without credentials")
    token = config.token.strip()
    if not token.isascii() or any(character.isspace() for character in token):
        raise InfluxDB3Error("influxdb3.token must be an ASCII token without whitespace")
    if not math.isfinite(config.timeout) or config.timeout <= 0:
        raise InfluxDB3Error("influxdb3.timeout must be a finite positive number")
