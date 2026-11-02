"""Exercise HTTP decoding and credential-safe failures without network access."""

import httpx
import pytest

from kazu.lib.usage import CollectionError
from kazu.sources import api_http


def test_get_json_request(monkeypatch):
    def request(url, **kwargs):
        assert url == "https://example.test/usage"
        assert kwargs == {
            "headers": {"Authorization": "Bearer fixture"},
            "timeout": 12,
            "params": {"limit": 1},
        }
        return httpx.Response(200, json={"total": 42})

    monkeypatch.setattr(api_http.httpx, "get", request)
    assert api_http.get_json(
        "https://example.test/usage",
        headers={"Authorization": "Bearer fixture"},
        timeout=12,
        params={"limit": 1},
    ) == {"total": 42}


@pytest.mark.parametrize(
    "response, message",
    [
        (httpx.Response(401, text="private credential"), "API query failed (HTTP 401)"),
        (httpx.Response(429), "API query failed (HTTP 429)"),
        (httpx.Response(302), "API query failed (HTTP 302)"),
        (httpx.Response(200, text="private credential"), "API did not return valid JSON"),
        (httpx.Response(200, json=[]), "API did not return a JSON object"),
    ],
)
def test_response_errors_are_safe(monkeypatch, response, message):
    monkeypatch.setattr(api_http.httpx, "get", lambda *a, **kw: response)
    with pytest.raises(CollectionError) as caught:
        api_http.get_json("https://example.test", headers={}, timeout=1)
    assert str(caught.value) == message


@pytest.mark.parametrize(
    "failure, detail",
    [
        (httpx.ConnectError("DNS lookup failed"), "ConnectError): DNS lookup failed"),
        (httpx.ReadTimeout(""), "ReadTimeout): request timeout=1s"),
        (httpx.ConnectError("private credential"), "ConnectError): [REDACTED]"),
        (httpx.ConnectError("Bearer private credential"), "ConnectError): [REDACTED]"),
    ],
)
def test_transport_error_is_safe(monkeypatch, failure, detail):
    def request(*args, **kwargs):
        raise failure

    monkeypatch.setattr(api_http.httpx, "get", request)
    with pytest.raises(CollectionError) as caught:
        api_http.get_json(
            "https://example.test",
            headers={"Authorization": "Bearer private credential"},
            timeout=1,
        )
    assert str(caught.value) == f"API request failed ({detail}"
