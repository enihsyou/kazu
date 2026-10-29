"""Keep CLI priority and explicit source selection when APIs are registered."""

import pytest

from kazu.config import SourceConfig
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources.search import API_COLLECTORS, CLI_COLLECTORS, SearchSource


@pytest.mark.parametrize(
    "selection, cli_fails, expected",
    [("auto", False, "cli"), ("auto", True, "api"), ("api", False, "api")],
)
def test_source_selection(monkeypatch, selection, cli_fails, expected):
    calls = []

    def cli(command, timeout):
        calls.append("cli")
        if cli_fails:
            raise CollectionError("CLI unavailable")
        return UsageSnapshot(())

    def api(config):
        calls.append("api")
        return UsageSnapshot(())

    monkeypatch.setitem(CLI_COLLECTORS, "firecrawl", ("firecrawl", cli))
    monkeypatch.setitem(API_COLLECTORS, "firecrawl", api)
    source = SearchSource("firecrawl", SourceConfig(source=selection))
    source.collect()
    assert source.mode == expected
    assert calls == (["cli", "api"] if cli_fails else [expected])


def test_explicit_cli_does_not_fall_back(monkeypatch):
    def cli(command, timeout):
        raise CollectionError("CLI unavailable")

    def api(config):
        pytest.fail("Explicit CLI selection must not call the API")

    monkeypatch.setitem(CLI_COLLECTORS, "firecrawl", ("firecrawl", cli))
    monkeypatch.setitem(API_COLLECTORS, "firecrawl", api)
    with pytest.raises(CollectionError, match="CLI unavailable"):
        SearchSource("firecrawl", SourceConfig(source="cli")).collect()
