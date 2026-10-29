"""Global source defaults and per-source overrides."""

import pytest

from kazu.config import SourceConfig, load_config


def test_source_defaults_and_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[sources]\nsource = "api"\ninterval = 45\ntimeout = 8\nidle_poll_limit = 2\n'
        "[sources.tinyfish]\nenabled = true\ninterval = 15\n"
        "[sources.ssp]\ntimeout = 12\n"
        '[sources.firecrawl]\nsource = "cli"\n',
        encoding="utf-8",
    )
    config = load_config(path)
    for source in (config.ssp, *config.providers.values()):
        assert source.idle_poll_limit == 2
    assert config.providers["tinyfish"].enabled
    assert config.providers["tinyfish"].interval == 15
    assert config.providers["tinyfish"].timeout == 8
    assert config.providers["tavily"].source == "api"
    assert config.providers["tavily"].interval == 45
    assert config.providers["firecrawl"].source == "cli"
    assert config.ssp.interval == 45
    assert config.ssp.timeout == 12

    # Loading overrides must not mutate the built-in defaults for the next load.
    defaults = load_config(tmp_path / "missing.toml")
    for source in (defaults.ssp, *defaults.providers.values()):
        assert not source.enabled
        assert source.source == SourceConfig().source
        assert source.interval == SourceConfig().interval
        assert source.timeout == SourceConfig().timeout
        assert source.idle_poll_limit == SourceConfig().idle_poll_limit


@pytest.mark.parametrize("settings", ["interval = 0", "timeout = -1", "idle_poll_limit = 0"])
def test_invalid_global_defaults_are_rejected(tmp_path, settings):
    path = tmp_path / "config.toml"
    path.write_text(f"[sources]\n{settings}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
