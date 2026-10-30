"""Device polling and token persistence across collector restarts."""

import json
import logging

import httpx
import pytest

from kazu.lib.usage import CollectionError
from kazu.sources import parallel_auth
from kazu.sources.parallel_auth import ParallelAuth


@pytest.fixture
def oauth(monkeypatch, tmp_path):
    now = [0.0]
    sleeps = []
    requests = []
    responses = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    def post(url, **kwargs):
        requests.append((url.rsplit("/getServiceKeys/", 1)[1], kwargs))
        status, body = responses.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(parallel_auth.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(parallel_auth.time, "time", lambda: 1000 + now[0])
    monkeypatch.setattr(parallel_auth.time, "sleep", sleep)
    monkeypatch.setattr(parallel_auth.httpx, "post", post)
    monkeypatch.setattr(
        parallel_auth, "get_json", lambda *args, **kwargs: {"credit_balance_cents": 1234}
    )
    return ParallelAuth(30, tmp_path / "parallel-oauth.json"), responses, requests, sleeps


def device(*, interval=5, expires_in=600):
    return 200, {
        "device_code": "device",
        "user_code": "CODE",
        "verification_uri": "https://platform.parallel.ai/verify",
        "verification_uri_complete": "https://platform.parallel.ai/verify?code=CODE",
        "expires_in": expires_in,
        "interval": interval,
    }


def token(refresh="refresh"):
    return 200, {"access_token": "access", "refresh_token": refresh, "expires_in": 3600}


def test_login_slow_down_and_restart(oauth, caplog):
    auth, responses, requests, sleeps = oauth
    responses.extend(
        [
            (200, {"client_id": "client"}),
            device(),
            (400, {"error": "authorization_pending"}),
            (400, {"error": "slow_down"}),
            (400, {"error": "slow_down"}),
            token(),
        ]
    )
    with caplog.at_level(logging.INFO, logger="kazu.sources.parallel_auth"):
        snapshot = auth.collect()
    assert snapshot.measurements[0].value == 12.34
    assert sleeps == [5, 5, 10, 15]
    assert "https://platform.parallel.ai/verify?code=CODE" in caplog.text
    assert "Parallel OAuth authorization succeeded." in caplog.text
    assert requests[1][1]["data"] == {"client_id": "client", "scope": "balance:read"}
    saved = json.loads(auth.path.read_text("utf-8"))
    assert saved["client_id"] == "client"
    assert saved["refresh_token"] == "refresh"
    assert saved["access_token_expires_at"] == 4635
    ParallelAuth(30, auth.path).collect()
    assert not responses
    assert len(requests) == 6  # Restart reused the saved access token without OAuth requests.


def test_authentication_failure_reports_missing_field(oauth):
    auth, responses, _, _ = oauth
    responses.append((200, {}))
    with pytest.raises(CollectionError, match="KeyError.*client_id"):
        auth.collect()


@pytest.mark.parametrize("rotate", [False, True])
def test_refresh_persists_for_next_restart(oauth, rotate):
    auth, responses, requests, sleeps = oauth
    auth.path.write_text(
        json.dumps({"client_id": "client", "refresh_token": "old", "access_token_expires_at": 0}),
        encoding="utf-8",
    )
    body = {"access_token": "access", "expires_in": 3600}
    if rotate:
        body["refresh_token"] = "new"
    responses.append((200, body))
    auth.collect()
    assert requests[0][1]["data"] == {"grant_type": "refresh_token", "refresh_token": "old"}
    assert json.loads(auth.path.read_text("utf-8"))["refresh_token"] == ("new" if rotate else "old")
    ParallelAuth(30, auth.path).collect()
    assert len(requests) == 1
    assert not sleeps


def test_invalid_refresh_starts_device_authorization(oauth):
    auth, responses, requests, sleeps = oauth
    auth.path.write_text(json.dumps({"client_id": "client", "refresh_token": "old"}), "utf-8")
    responses.extend([(400, {"error": "invalid_grant"}), device(), token("new")])
    auth.collect()
    assert [endpoint for endpoint, _ in requests] == ["token", "device/code", "token"]
    assert json.loads(auth.path.read_text("utf-8"))["refresh_token"] == "new"


@pytest.mark.parametrize("error", ["access_denied", "server_error"])
def test_terminal_errors_stop_polling(oauth, error):
    auth, responses, requests, sleeps = oauth
    responses.extend([(200, {"client_id": "client"}), device(), (400, {"error": error})])
    with pytest.raises(CollectionError):
        auth.collect()
    assert sleeps == [5]
    assert len(requests) == 3


def test_polling_stops_at_five_minutes(oauth):
    auth, responses, requests, sleeps = oauth
    responses.extend(
        [
            (200, {"client_id": "client"}),
            device(interval=7),
            *[(400, {"error": "authorization_pending"})] * 42,
        ]
    )
    with pytest.raises(CollectionError, match="timed out"):
        auth.collect()
    assert sum(sleeps) == 300
    assert sleeps[:-1] == [7] * 42
    assert sleeps[-1] == 6
    assert not responses


def test_expired_device_restarts_within_original_deadline(oauth):
    auth, responses, requests, sleeps = oauth
    responses.extend(
        [
            (200, {"client_id": "client"}),
            device(),
            (400, {"error": "expired_token"}),
            device(expires_in=2),
            device(),
            token(),
        ]
    )
    auth.collect()
    assert sleeps == [5, 2, 5]
    assert [endpoint for endpoint, _ in requests].count("device/code") == 3
