from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

APP_NAME = "kazu"
"""Application name used for configuration and command-line metadata."""
APP_AUTHOR = "KokomiNetwork"
"""Application author used when resolving the user configuration directory."""


@dataclass(frozen=True)
class InfluxDB3Config:
    """Configuration values for the optional InfluxDB 3 writer."""

    host: str
    """InfluxDB 3 server URL."""
    database: str
    """InfluxDB 3 database name."""
    token: str
    """InfluxDB 3 authentication token."""
    timeout: float
    """InfluxDB 3 request timeout in seconds."""


@dataclass(frozen=True)
class SSPConfig:
    """Configuration values for the SSP traffic source."""

    authorization: str
    """Complete SSP authorization header value."""
    api_base_url: str
    """SSP API base URL."""
    gateway_base_url: str
    """Encrypted gateway base URL."""
    timeout: float
    """SSP request timeout in seconds."""


@dataclass(frozen=True)
class AppConfig:
    """Complete application configuration."""

    influxdb3: InfluxDB3Config
    """Optional InfluxDB 3 configuration."""
    ssp: SSPConfig
    """SSP source configuration."""


def _read_default_config_text() -> str:
    return resources.files(APP_NAME).joinpath("default_config.toml").read_text(encoding="utf-8")


DEFAULT_CONFIG_TOML = _read_default_config_text()
"""Built-in TOML configuration text."""
DEFAULT_CONFIG_DATA: dict[str, Any] = tomllib.loads(DEFAULT_CONFIG_TOML)
"""Parsed built-in configuration values."""


def get_config_path() -> Path:
    """Return the path to the user configuration file."""
    config_dir = user_config_path(appname=APP_NAME, appauthor=APP_AUTHOR, ensure_exists=False)
    return config_dir / "config.toml"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_positive_float(value: Any, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    return default


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        base_value = result.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            result[key] = _deep_merge(base_value, value)
        else:
            result[key] = value
    return result


def load_config() -> AppConfig:
    """Load and validate merged built-in and user configuration values."""
    user_data = _load_user_config()
    merged = _deep_merge(DEFAULT_CONFIG_DATA, user_data)
    influxdb = _as_dict(merged.get("influxdb3"))
    ssp = _as_dict(_as_dict(merged.get("sources")).get("ssp"))

    return AppConfig(
        influxdb3=InfluxDB3Config(
            host=_as_str(influxdb.get("host")),
            database=_as_str(influxdb.get("database")),
            token=_as_str(influxdb.get("token")),
            timeout=_as_positive_float(influxdb.get("timeout"), 15.0),
        ),
        ssp=SSPConfig(
            authorization=_as_str(ssp.get("authorization")),
            api_base_url=_as_str(ssp.get("api_base_url")),
            gateway_base_url=_as_str(ssp.get("gateway_base_url")),
            timeout=_as_positive_float(ssp.get("timeout"), 15.0),
        ),
    )


def _load_user_config() -> dict[str, Any]:
    path = get_config_path()
    try:
        if path.exists():
            return _as_dict(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return {}
