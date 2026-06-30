from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import tomllib
from platformdirs import user_config_path


APP_NAME = "kazu"
APP_AUTHOR = "KokomiNetwork"


@dataclass(frozen=True)
class InfluxDB3Config:
	host: str
	database: str
	token: str
	org: str


@dataclass(frozen=True)
class SSPConfig:
	default_domain: str
	url: str
	session: str
	account: str


@dataclass(frozen=True)
class AppConfig:
	influxdb3: InfluxDB3Config
	ssp: SSPConfig


def _read_default_config_text() -> str:
	return resources.files(APP_NAME).joinpath("default_config.toml").read_text(encoding="utf-8")


DEFAULT_CONFIG_TOML = _read_default_config_text()

DEFAULT_CONFIG_DATA: dict[str, Any] = tomllib.loads(DEFAULT_CONFIG_TOML)


def get_config_path() -> Path:
	config_dir = user_config_path(appname=APP_NAME, appauthor=APP_AUTHOR, ensure_exists=False)
	return config_dir / "config.toml"


def _as_dict(value: Any) -> dict[str, Any]:
	return value if isinstance(value, dict) else {}


def _as_str(value: Any) -> str:
	return value if isinstance(value, str) else ""


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
	path = get_config_path()
	user_data: dict[str, Any] = {}

	try:
		if path.exists():
			user_data = tomllib.loads(path.read_text(encoding="utf-8"))
	except (OSError, tomllib.TOMLDecodeError):
		user_data = {}

	merged = _deep_merge(DEFAULT_CONFIG_DATA, _as_dict(user_data))
	influx = _as_dict(merged.get("influxdb3"))
	sources = _as_dict(merged.get("sources"))
	ssp = _as_dict(sources.get("ssp"))

	return AppConfig(
		influxdb3=InfluxDB3Config(
			host=_as_str(influx.get("host")),
			database=_as_str(influx.get("database")),
			token=_as_str(influx.get("token")),
			org=_as_str(influx.get("org")),
		),
		ssp=SSPConfig(
			default_domain=_as_str(ssp.get("default_domain")),
			url=_as_str(ssp.get("url")),
			session=_as_str(ssp.get("session")),
			account=_as_str(ssp.get("account")),
		),
	)
