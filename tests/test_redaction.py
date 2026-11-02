"""Credential redaction for configured values and formatted log arguments."""

import io
import logging

import pytest

from kazu.config import load_config
from kazu.lib import redaction


@pytest.fixture(autouse=True)
def isolated_secrets(monkeypatch):
    monkeypatch.setattr(redaction, "_REGISTERED_SECRETS", set())


@pytest.mark.parametrize(
    "name",
    [
        "TAVILY_API_KEY",
        "ANOTHER_APIKEY",
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
        "CLIENT_SECRET",
        "SERVICE_KEY",
        "DB_PASSWORD",
    ],
)
def test_environment_secret_is_hidden_without_its_name(monkeypatch, name):
    monkeypatch.setenv(name, "fixture-env-secret")
    assert redaction.redact("Connection failed: fixture-env-secret") == (
        "Connection failed: [REDACTED]"
    )


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "Basic"])
def test_authorization_hides_full_header_and_bare_credential(scheme):
    header = f"{scheme} fixture-auth-secret"
    assert (
        redaction.redact(f"{header}; credential=fixture-auth-secret", {"Authorization": header})
        == "[REDACTED]; credential=[REDACTED]"
    )


def test_cookie_values_are_hidden_individually(monkeypatch):
    cookie = 'session=fixture-session; csrf="fixture-csrf"; empty=""'
    monkeypatch.setenv("SERVICE_COOKIE", cookie)
    assert redaction.redact(f"{cookie}\nfixture-session / fixture-csrf") == (
        "[REDACTED]\n[REDACTED] / [REDACTED]"
    )


def test_dotenv_secrets_are_registered(tmp_path):
    path = tmp_path / "config.toml"
    path.with_name(".env").write_text(
        "OTHER_API_KEY=fixture-dotenv-key\nOTHER_COOKIE=sid=fixture-dotenv-session\n",
        encoding="utf-8",
    )
    load_config(path)
    assert redaction.redact("fixture-dotenv-key / fixture-dotenv-session") == (
        "[REDACTED] / [REDACTED]"
    )


def test_non_secret_values_and_empty_credentials_are_unchanged(monkeypatch):
    monkeypatch.setenv("SERVICE_HOST", "example.test")
    monkeypatch.setenv("EMPTY_API_KEY", "")
    assert redaction.redact("DNS lookup failed: example.test", {"Cookie": 'sid=""'}) == (
        "DNS lookup failed: example.test"
    )


def test_logging_filter_redacts_interpolated_arguments(monkeypatch):
    monkeypatch.setenv("SERVICE_API_KEY", "fixture-log-secret")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(redaction.RedactingFilter())
    logger = logging.Logger("fixture")
    logger.addHandler(handler)
    logger.warning("Query failed: %s (HTTP %d)", "fixture-log-secret", 401)
    assert output.getvalue() == "Query failed: [REDACTED] (HTTP 401)\n"
