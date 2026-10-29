"""Firecrawl credit response fixtures and GET/authentication contract."""

from __future__ import annotations

import pytest

from kazu.config import SourceConfig
from kazu.lib.usage import CollectionError
from kazu.sources import firecrawl_api


@pytest.fixture
def response(monkeypatch):
    payload = {"success": True, "data": {"remainingCredits": 700, "planCredits": 500}}
    calls = []

    def get_json(url, *, headers, timeout, params=None):
        assert url == "https://api.firecrawl.dev/v2/team/credit-usage"
        assert headers == {"Authorization": "Bearer fixture-key"}
        assert timeout == 7
        assert params is None
        calls.append(url)
        return payload

    monkeypatch.setattr(firecrawl_api, "get_json", get_json)
    return payload, calls


def test_collect_remaining_and_plan_without_inventing_used_credits(response):
    snapshot = firecrawl_api.collect(SourceConfig(api_key="fixture-key", timeout=7))
    assert [(m.name, m.value, dict(m.labels)) for m in snapshot.measurements] == [
        ("kazu_search_credits_remaining", 700.0, {"scope": "account"}),
        ("kazu_search_credits_cap", 500.0, {"scope": "plan"}),
    ]
    assert snapshot.warnings == ()
    assert len(response[1]) == 1


@pytest.mark.parametrize("plan", [0, -1])
def test_only_positive_plan_credits_are_exposed(response, plan):
    response[0]["data"]["planCredits"] = plan
    snapshot = firecrawl_api.collect(SourceConfig(api_key="fixture-key", timeout=7))
    assert [m.name for m in snapshot.measurements] == ["kazu_search_credits_remaining"]


@pytest.mark.parametrize("field", ["remainingCredits", "planCredits"])
@pytest.mark.parametrize("value", [True, None, "fixture-key", float("inf"), float("nan")])
def test_invalid_numeric_fields_fail_safely(response, field, value):
    response[0]["data"][field] = value
    with pytest.raises(CollectionError) as error:
        firecrawl_api.collect(SourceConfig(api_key="fixture-key", timeout=7))
    assert str(error.value) == "Unexpected Firecrawl credit response schema"
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"success": False, "error": "fixture-key raw response"},
        {"success": 1, "data": {"remainingCredits": 1}},
        {"success": True, "data": None},
        {"success": True, "data": []},
        {"success": True, "data": {"planCredits": 500}},
        {"success": True, "data": {"remainingCredits": 700}},
    ],
)
def test_missing_required_fields_and_unsuccessful_response_fail(response, payload):
    response[0].clear()
    response[0].update(payload)
    with pytest.raises(CollectionError, match="Unexpected Firecrawl credit response schema"):
        firecrawl_api.collect(SourceConfig(api_key="fixture-key", timeout=7))


@pytest.mark.parametrize("key", ["", "   "])
def test_missing_credentials_fail_before_request(response, key):
    with pytest.raises(CollectionError, match="FIRECRAWL_API_KEY is required"):
        firecrawl_api.collect(SourceConfig(api_key=key))
    assert response[1] == []
