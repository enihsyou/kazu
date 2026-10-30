"""Select configured APIs before available CLIs."""

import pytest

from kazu.config import SourceConfig
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources import search
from kazu.sources.search import API_COLLECTORS, CLI_COLLECTORS, SearchSource


@pytest.mark.parametrize(
    "selection, api_key, expected",
    [("auto", "key", "api"), ("auto", "", "cli"), ("api", "", "api")],
)
def test_source_selection(monkeypatch, selection, api_key, expected):
    calls = []

    def cli(command, timeout):
        calls.append("cli")
        return UsageSnapshot(())

    def api(config):
        calls.append("api")
        return UsageSnapshot(())

    monkeypatch.setitem(CLI_COLLECTORS, "firecrawl", ("firecrawl", cli))
    monkeypatch.setitem(API_COLLECTORS, "firecrawl", api)
    monkeypatch.setattr(search.shutil, "which", lambda command: command)
    source = SearchSource("firecrawl", SourceConfig(source=selection, api_key=api_key))
    source.collect()
    assert source.mode == expected
    assert calls == [expected]


def test_explicit_cli_does_not_fall_back(monkeypatch):
    def cli(command, timeout):
        raise CollectionError("CLI unavailable")

    def api(config):
        pytest.fail("Explicit CLI selection must not call the API")

    monkeypatch.setitem(CLI_COLLECTORS, "firecrawl", ("firecrawl", cli))
    monkeypatch.setitem(API_COLLECTORS, "firecrawl", api)
    with pytest.raises(CollectionError, match="CLI unavailable"):
        SearchSource("firecrawl", SourceConfig(source="cli")).collect()


def test_parallel_only_reads_balance(monkeypatch):
    def run_json(command, args, timeout):
        assert (command, args, timeout) == ("parallel-cli", ["balance", "--json", "get"], 30)
        return {"credit_balance_cents": 1234}

    monkeypatch.setattr(search, "_run_json", run_json)
    snapshot = SearchSource("parallel", SourceConfig(source="cli")).collect()
    assert [(m.name, m.value, dict(m.labels)) for m in snapshot.measurements] == [
        ("kazu_search_money_remaining", 12.34, {"currency": "USD", "scope": "account"})
    ]


@pytest.mark.parametrize("selection", ["auto", "oauth"])
def test_parallel_oauth_selection(monkeypatch, tmp_path, selection):
    monkeypatch.setattr(search.shutil, "which", lambda command: None)
    path = tmp_path / "parallel-oauth.json"
    source = SearchSource("parallel", SourceConfig(source=selection), oauth_path=path)
    assert source.mode == "oauth"
    assert source.auth.path == path


def test_oauth_is_not_supported_for_other_providers():
    with pytest.raises(CollectionError, match="oauth is not supported"):
        SearchSource("tavily", SourceConfig(source="oauth")).collect()
