"""Tavily's documented usage fixture and collector request contract."""

from __future__ import annotations

import traceback
from typing import Any

import httpx
import pytest

from kazu.config import SourceConfig
from kazu.lib.measurements import CREDITS_CAP, CREDITS_REMAINING, CREDITS_USED
from kazu.lib.usage import CollectionError
from kazu.sources import tavily_api


@pytest.fixture
def usage() -> dict[str, Any]:
    # https://docs.tavily.com/documentation/api-reference/endpoint/usage
    return {
        "key": {
            "usage": 150,
            "limit": 1000,
            "search_usage": 100,
            "extract_usage": 25,
            "crawl_usage": 15,
            "map_usage": 7,
            "research_usage": 3,
        },
        "account": {
            "current_plan": "Bootstrap",
            "plan_usage": 500,
            "plan_limit": 15000,
            "paygo_usage": 25,
            "paygo_limit": 100,
            "search_usage": 350,
            "extract_usage": 75,
            "crawl_usage": 50,
            "map_usage": 15,
            "research_usage": 10,
        },
    }


@pytest.fixture
def response(monkeypatch, usage):
    monkeypatch.setattr(tavily_api, "get_json", lambda *args, **kwargs: usage)
    return usage


def _values(snapshot):
    return {(m.name, dict(m.labels)["scope"]): m.value for m in snapshot.measurements}


def test_request_and_documented_usage(monkeypatch, usage):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=usage)

    # Exercise the collector's helper arguments without depending on its HTTP internals.
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:

        def get_json(url, *, headers, timeout, params=None):
            assert timeout == 7
            assert params is None
            return client.get(url, headers=headers, timeout=timeout, params=params).json()

        monkeypatch.setattr(tavily_api, "get_json", get_json)
        snapshot = tavily_api.collect(SourceConfig(api_key="fixture-key", timeout=7))

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://api.tavily.com/usage"
    assert requests[0].headers["Authorization"] == "Bearer fixture-key"
    assert _values(snapshot) == {
        (CREDITS_USED.name, "key"): 150,
        (CREDITS_CAP.name, "key"): 1000,
        (CREDITS_REMAINING.name, "key"): 850,
        (CREDITS_USED.name, "plan"): 500,
        (CREDITS_CAP.name, "plan"): 15000,
        (CREDITS_REMAINING.name, "plan"): 14500,
        (CREDITS_USED.name, "paygo"): 25,
        (CREDITS_CAP.name, "paygo"): 100,
        (CREDITS_REMAINING.name, "paygo"): 75,
    }
    assert not snapshot.warnings


@pytest.mark.parametrize("limit", [None, 0, 100])
def test_unlimited_zero_and_exceeded_key_limit(response, limit):
    response["key"]["limit"] = limit
    values = _values(tavily_api.collect(SourceConfig(api_key="fixture-key")))
    assert values[CREDITS_USED.name, "key"] == 150
    if limit is None:
        assert (CREDITS_CAP.name, "key") not in values
        assert (CREDITS_REMAINING.name, "key") not in values
    else:
        assert values[CREDITS_CAP.name, "key"] == limit
        assert values[CREDITS_REMAINING.name, "key"] == 0


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("key", "usage"),
        ("key", "limit"),
        ("account", "plan_usage"),
        ("account", "plan_limit"),
        ("account", "paygo_usage"),
        ("account", "paygo_limit"),
    ],
)
@pytest.mark.parametrize("value", [True, "secret-response", -1, float("nan"), float("inf")])
def test_invalid_numbers_are_safe_errors(response, section, field, value):
    response[section][field] = value
    with pytest.raises(CollectionError, match="invalid schema") as error:
        tavily_api.collect(SourceConfig(api_key="fixture-key"))
    formatted = "".join(traceback.format_exception(error.value))
    assert "secret-response" not in formatted
    assert "fixture-key" not in formatted


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("key", "usage"),
        ("key", "limit"),
        ("account", "plan_usage"),
        ("account", "plan_limit"),
        ("account", "paygo_usage"),
        ("account", "paygo_limit"),
    ],
)
def test_missing_required_values_fail(response, section, field):
    del response[section][field]
    with pytest.raises(CollectionError, match="invalid schema"):
        tavily_api.collect(SourceConfig(api_key="fixture-key"))


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("key", "usage"),
        ("account", "plan_usage"),
        ("account", "plan_limit"),
        ("account", "paygo_usage"),
        ("account", "paygo_limit"),
    ],
)
def test_null_required_numbers_fail(response, section, field):
    response[section][field] = None
    with pytest.raises(CollectionError, match="invalid schema"):
        tavily_api.collect(SourceConfig(api_key="fixture-key"))


def test_optional_endpoint_usage_is_not_required(response):
    for section in response.values():
        for field in list(section):
            if field in {
                "current_plan",
                "search_usage",
                "extract_usage",
                "crawl_usage",
                "map_usage",
                "research_usage",
            }:
                del section[field]
    assert len(tavily_api.collect(SourceConfig(api_key="fixture-key")).measurements) == 9


@pytest.mark.parametrize("section", ["key", "account"])
@pytest.mark.parametrize("value", [None, [], "secret-response"])
def test_invalid_sections_fail(response, section, value):
    response[section] = value
    with pytest.raises(CollectionError, match="invalid schema"):
        tavily_api.collect(SourceConfig(api_key="fixture-key"))


@pytest.mark.parametrize("api_key", ["", "   "])
def test_missing_credentials_do_not_call_http(monkeypatch, api_key):
    def unexpected_request(*args, **kwargs):
        pytest.fail("Missing credentials must be rejected before HTTP")

    monkeypatch.setattr(tavily_api, "get_json", unexpected_request)
    with pytest.raises(CollectionError, match="API key is required"):
        tavily_api.collect(SourceConfig(api_key=api_key))


def test_http_errors_propagate(monkeypatch):
    def failed_request(*args, **kwargs):
        raise CollectionError("HTTP request failed (401)")

    monkeypatch.setattr(tavily_api, "get_json", failed_request)
    with pytest.raises(CollectionError, match=r"HTTP request failed \(401\)"):
        tavily_api.collect(SourceConfig(api_key="fixture-key"))
