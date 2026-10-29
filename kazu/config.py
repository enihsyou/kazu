"""Defaulted public configuration and credentials from the adjacent .env file."""

from __future__ import annotations

import math
import os
import re
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from platformdirs import user_config_path

APP_NAME = "kazu"
APP_AUTHOR = "KokomiNetwork"
PROVIDERS = ("exa", "tinyfish", "tavily", "firecrawl", "parallel")


@dataclass(frozen=True)
class SourceConfig:
    enabled: bool = False
    source: str = "auto"
    interval: float = 120.0
    timeout: float = 30.0
    idle_poll_limit: int = 5
    command: str = ""
    api_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if self.source not in {"auto", "cli", "api"}:
            raise ValueError("source must be auto, cli, or api")
        for name in ("interval", "timeout"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")
        if type(self.idle_poll_limit) is not int or self.idle_poll_limit < 1:
            raise ValueError("idle_poll_limit must be a positive integer")


@dataclass(frozen=True)
class ExaConfig(SourceConfig):
    service_key: str = field(default="", repr=False)
    api_key_id: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.api_key_id, str) or (
            self.api_key_id
            and not re.fullmatch(
                r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", self.api_key_id
            )
        ):
            raise ValueError("sources.exa.api_key_id must be a hyphenated UUID")


@dataclass(frozen=True)
class SSPConfig(SourceConfig):
    authorization: str = field(default="", repr=False)
    api_base_url: str = "https://s1.thefew01.top/api/v1"
    gateway_base_url: str = "https://x1.thecores.top"


@dataclass(frozen=True)
class MetricsConfig:
    host: str = "127.0.0.1"
    port: int = 9101


@dataclass(frozen=True)
class AppConfig:
    metrics: MetricsConfig
    ssp: SSPConfig
    providers: dict[str, SourceConfig]


DEFAULT_CONFIG_TOML = resources.files(APP_NAME).joinpath("default_config.toml").read_text("utf-8")
DEFAULT_CONFIG_DATA: dict[str, Any] = tomllib.loads(DEFAULT_CONFIG_TOML)


def get_config_path() -> Path:
    return user_config_path(appname=APP_NAME, appauthor=APP_AUTHOR) / "config.toml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> AppConfig:
    path = get_config_path() if path is None else path
    user_data = tomllib.loads(path.read_text("utf-8")) if path.exists() else {}
    unknown = user_data.keys() - {"metrics", "sources"}
    if unknown:
        raise ValueError(f"Unknown configuration sections: {', '.join(sorted(unknown))}")
    merged = _deep_merge(DEFAULT_CONFIG_DATA, user_data)
    env_path = path.parent / ".env"
    secrets = dotenv_values(env_path, interpolate=False) if env_path.exists() else {}

    def credential(name: str) -> str:
        return os.environ.get(name, secrets.get(name) or "")

    sources = merged["sources"]
    unknown = sources.keys() - {"ssp", *PROVIDERS}
    if unknown:
        raise ValueError(f"Unknown sources: {', '.join(sorted(unknown))}")
    for name, values in sources.items():
        if {"api_key", "authorization", "token", "service_key"} & values.keys():
            raise ValueError(f"sources.{name}: credentials belong in {env_path}, not TOML")
    return AppConfig(
        metrics=MetricsConfig(**merged["metrics"]),
        ssp=SSPConfig(**sources["ssp"], authorization=credential("SSP_AUTHORIZATION")),
        providers={
            name: (
                ExaConfig(
                    **sources[name],
                    api_key=credential("EXA_API_KEY"),
                    service_key=credential("EXA_SERVICE_KEY"),
                )
                if name == "exa"
                else SourceConfig(**sources[name], api_key=credential(f"{name.upper()}_API_KEY"))
            )
            for name in PROVIDERS
        },
    )
