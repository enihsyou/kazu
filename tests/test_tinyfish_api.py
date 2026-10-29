"""TinyFish API request contracts and independent-query parsing fixtures."""

from __future__ import annotations

import pytest

from kazu.config import SourceConfig
from kazu.lib.usage import CollectionError
from kazu.sources import tinyfish_api


@pytest.fixture
def responses(monkeypatch):
    payloads = {
        "wallet": {"available_balance": "21.44", "currency": "USD"},
        "search": {"total": 123, "items": [], "page": 1, "total_pages": 123},
    }
    calls = []

    def get_json(url, *, headers, timeout, params=None):
        assert headers == {"X-API-Key": "fixture-key"}
        assert timeout == 7
        if url == "https://agent.tinyfish.ai/v1/wallet":
            query = "wallet"
            assert params is None
        else:
            assert url == "https://agent.tinyfish.ai/v1/search/usage"
            assert params == {"limit": 1}
            query = "search"
        calls.append(query)
        payload = payloads[query]
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(tinyfish_api, "get_json", get_json)
    return payloads, calls


def test_collect_wallet_and_total_history(responses):
    snapshot = tinyfish_api.collect(SourceConfig(api_key="fixture-key", timeout=7))
    assert [(m.name, m.value, dict(m.labels)) for m in snapshot.measurements] == [
        ("kazu_search_money_remaining", 21.44, {"currency": "USD", "scope": "account"}),
        ("kazu_search_calls_used", 123.0, {"scope": "all_time"}),
    ]
    assert snapshot.warnings == ()
    assert responses[1] == ["wallet", "search"]


def test_overdrawn_wallet_is_preserved(responses):
    responses[0]["wallet"]["available_balance"] = "-0.25"
    snapshot = tinyfish_api.collect(SourceConfig(api_key="fixture-key", timeout=7))
    assert snapshot.measurements[0].value == -0.25


@pytest.mark.parametrize("query", ["wallet", "search"])
@pytest.mark.parametrize("failure", [CollectionError("fixture-key raw response"), {}])
def test_independent_query_failure_returns_partial_snapshot(responses, query, failure):
    responses[0][query] = failure
    snapshot = tinyfish_api.collect(SourceConfig(api_key="fixture-key", timeout=7))
    assert len(snapshot.measurements) == 1
    assert len(snapshot.warnings) == 1
    assert snapshot.warnings[0].startswith(f"{query}:")
    assert "fixture-key" not in snapshot.warnings[0]
    assert responses[1] == ["wallet", "search"]


@pytest.mark.parametrize(
    ("query", "payload"),
    [
        ("wallet", {"available_balance": "NaN", "currency": "USD"}),
        ("wallet", {"available_balance": "inf", "currency": "USD"}),
        ("wallet", {"available_balance": True, "currency": "USD"}),
        ("wallet", {"available_balance": "1", "currency": None}),
        ("wallet", {"available_balance": "1", "currency": ""}),
        ("wallet", {"available_balance": "fixture-key", "currency": "USD"}),
        ("search", {"total": True}),
        ("search", {"total": float("nan")}),
        ("search", {"total": float("inf")}),
        ("search", {"total": "123"}),
        ("search", {"total": -1}),
    ],
)
def test_invalid_metric_values_are_omitted_with_safe_warning(responses, query, payload):
    responses[0][query] = payload
    snapshot = tinyfish_api.collect(SourceConfig(api_key="fixture-key", timeout=7))
    assert len(snapshot.measurements) == 1
    assert snapshot.warnings == (f"{query}: Unexpected API response schema",)


def test_both_queries_must_not_fail(responses):
    responses[0].update(wallet={}, search=CollectionError("fixture-key raw response"))
    with pytest.raises(CollectionError) as error:
        tinyfish_api.collect(SourceConfig(api_key="fixture-key", timeout=7))
    assert str(error.value) == ("wallet: Unexpected API response schema; search: API query failed")


@pytest.mark.parametrize("key", ["", "   "])
def test_missing_credentials_fail_before_request(responses, key):
    with pytest.raises(CollectionError, match="TINYFISH_API_KEY is required"):
        tinyfish_api.collect(SourceConfig(api_key=key))
    assert responses[1] == []
