"""Offline Exa response and configuration contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from kazu.config import ExaConfig, SourceConfig, load_config
from kazu.lib.usage import CollectionError
from kazu.sources import exa_api

KEY_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def config():
    return ExaConfig(service_key="fixture-service", api_key="fixture-search", api_key_id=KEY_ID)


@pytest.fixture
def usage_response():
    return {
        "api_key_id": KEY_ID,
        "period": {"start": "2025-01-01T00:00:00Z", "end": "2025-01-31T23:59:59Z"},
        "total_cost_usd": 45.67,
        "cost_breakdown": [
            {"price_name": "Neural Search", "quantity": 1000, "amount_usd": 30},
            {"price_name": "Content Retrieval", "quantity": 500, "amount_usd": 15.67},
        ],
    }


def test_collect_request_and_money_only(monkeypatch, config, usage_response):
    requests = []

    def get_json(url, **kwargs):
        requests.append((url, kwargs))
        return usage_response

    monkeypatch.setattr(exa_api, "get_json", get_json)
    snapshot = exa_api.collect(config)
    assert requests == [
        (
            f"https://admin-api.exa.ai/team-management/api-keys/{KEY_ID}/usage",
            {"headers": {"x-api-key": config.service_key}, "timeout": config.timeout},
        )
    ]
    assert len(snapshot.measurements) == 1
    metric = snapshot.measurements[0]
    assert metric.name == "kazu_search_money_used"
    assert metric.value == 45.67
    assert dict(metric.labels) == {"currency": "USD", "scope": "key_30d"}
    assert snapshot.warnings == ()


def test_collect_zero_without_breakdown(monkeypatch, config):
    monkeypatch.setattr(exa_api, "get_json", lambda *a, **kw: {"total_cost_usd": 0})
    assert exa_api.collect(config).measurements[0].value == 0


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"total_cost_usd": None},
        {"total_cost_usd": True},
        {"total_cost_usd": "45.67"},
        {"total_cost_usd": float("nan")},
        {"total_cost_usd": float("inf")},
        {"total_cost_usd": -1},
        {"total_cost_usd": 10**400},
        {"total_cost_usd": {}},
    ],
)
def test_invalid_cost_is_safe_error(monkeypatch, config, data):
    monkeypatch.setattr(exa_api, "get_json", lambda *a, **kw: data)
    with pytest.raises(CollectionError, match="^Exa usage response has invalid total_cost_usd$"):
        exa_api.collect(config)


@pytest.mark.parametrize("missing", ["service_key", "api_key_id"])
def test_missing_configuration_fails_before_http(monkeypatch, config, missing):
    def unexpected_request(*args, **kwargs):
        pytest.fail("Missing configuration must fail before HTTP")

    monkeypatch.setattr(exa_api, "get_json", unexpected_request)
    with pytest.raises(CollectionError):
        exa_api.collect(replace(config, **{missing: ""}))
    with pytest.raises(CollectionError, match="EXA_SERVICE_KEY"):
        exa_api.collect(SourceConfig(api_key="fixture-search"))


def test_http_collection_error_propagates(monkeypatch, config):
    def get_json(*args, **kwargs):
        raise CollectionError("HTTP request failed")

    monkeypatch.setattr(exa_api, "get_json", get_json)
    with pytest.raises(CollectionError, match="^HTTP request failed$"):
        exa_api.collect(config)


@pytest.mark.parametrize(
    "key_id", ["../usage", "a/b", "a?b", "a#b", "550e8400e29b41d4a716446655440000", 5]
)
def test_config_rejects_unsafe_or_non_uuid_id(key_id):
    with pytest.raises(ValueError, match="hyphenated UUID"):
        ExaConfig(api_key_id=key_id)


def test_load_credentials_from_adjacent_dotenv_and_environment(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(f'[sources.exa]\napi_key_id = "{KEY_ID}"\n', encoding="utf-8")
    (tmp_path / ".env").write_text(
        "EXA_SERVICE_KEY=fixture-dotenv-service\nEXA_API_KEY=fixture-dotenv-search\n",
        encoding="utf-8",
    )
    for name in ("EXA_SERVICE_KEY", "EXA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = load_config(path).providers["exa"]
    assert isinstance(config, ExaConfig)
    assert config.api_key_id == KEY_ID
    assert config.service_key == "fixture-dotenv-service"
    assert config.api_key == "fixture-dotenv-search"
    assert config.service_key not in repr(config)
    assert config.api_key not in repr(config)

    monkeypatch.setenv("EXA_SERVICE_KEY", "fixture-env-service")
    monkeypatch.setenv("EXA_API_KEY", "fixture-env-search")
    config = load_config(path).providers["exa"]
    assert config.service_key == "fixture-env-service"
    assert config.api_key == "fixture-env-search"

    monkeypatch.setenv("EXA_SERVICE_KEY", "")
    assert load_config(path).providers["exa"].service_key == ""


def test_search_key_never_becomes_service_key(tmp_path, monkeypatch):
    monkeypatch.delenv("EXA_SERVICE_KEY", raising=False)
    monkeypatch.setenv("EXA_API_KEY", "fixture-search")
    config = load_config(tmp_path / "config.toml").providers["exa"]
    assert isinstance(config, ExaConfig)
    assert config.service_key == ""
    assert config.api_key == "fixture-search"


@pytest.mark.parametrize("field", ["service_key", "api_key", "authorization", "token"])
def test_toml_secrets_rejected_without_value(tmp_path, field):
    path = tmp_path / "config.toml"
    secret = "fixture-rejected-credential"
    path.write_text(f'[sources.exa]\n{field} = "{secret}"\n', encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_config(path)
    assert "credentials belong in" in str(caught.value)
    assert secret not in str(caught.value)
