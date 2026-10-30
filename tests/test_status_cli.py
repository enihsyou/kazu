"""Status updates completed rows without changing configured source order."""

import argparse
import json
from dataclasses import asdict
from io import StringIO
from threading import Event

from rich.console import Console

from kazu.clicmds import status_cli
from kazu.config import SourceConfig
from kazu.lib.measurements import TRAFFIC_METRICS
from kazu.lib.usage import CollectionError, UsageSnapshot


def test_terminal_updates_fast_result_while_slow_query_is_pending(monkeypatch):
    settings = {name: SourceConfig(enabled=True) for name in ("slow", "fast", "broken")}
    slow_started = Event()
    release_slow = Event()
    frames = []
    render_table = status_cli._render_table

    class Source:
        mode = "api"

        def __init__(self, name):
            self.name = name

        def collect(self):
            if self.name == "slow":
                slow_started.set()
                release_slow.wait(timeout=5)
            elif self.name == "fast":
                assert slow_started.wait(timeout=5)
            else:
                raise CollectionError("Query failed")
            return UsageSnapshot(())

        def close(self):
            pass

    def render(results):
        frame = [(result["provider"], result["status"]) for result in results]
        frames.append(frame)
        if frame == [("slow", "loading"), ("fast", "ok"), ("broken", "error")]:
            release_slow.set()
        return render_table(results)

    console = Console(file=StringIO(), force_terminal=True)
    monkeypatch.setattr(status_cli, "Console", lambda **kwargs: console)
    monkeypatch.setattr(status_cli, "load_config", lambda path: object())
    monkeypatch.setattr(status_cli, "source_configs", lambda config: settings)
    monkeypatch.setattr(status_cli, "create_source", lambda name, config: Source(name))
    monkeypatch.setattr(status_cli, "_render_table", render)

    result = status_cli.StatusCommand()._run(argparse.Namespace(config=None, json=False))

    assert result == 1
    assert frames[0] == [("slow", "loading"), ("fast", "loading"), ("broken", "loading")]
    assert release_slow.is_set()
    assert frames[-1] == [("slow", "ok"), ("fast", "ok"), ("broken", "error")]
    assert all([name for name, status in frame] == list(settings) for frame in frames)


def test_json_keeps_final_results_without_live_display(monkeypatch, capsys):
    settings = {name: SourceConfig() for name in ("second", "first")}
    console = Console(file=StringIO(), force_terminal=True)
    monkeypatch.setattr(status_cli, "Console", lambda **kwargs: console)
    monkeypatch.setattr(status_cli, "load_config", lambda path: object())
    monkeypatch.setattr(status_cli, "source_configs", lambda config: settings)

    def unexpected_live(*args, **kwargs):
        raise AssertionError("JSON must not start a live display")

    monkeypatch.setattr(status_cli, "Live", unexpected_live)
    result = status_cli.StatusCommand()._run(argparse.Namespace(config=None, json=True))

    assert result == 0
    results = json.loads(capsys.readouterr().out)
    assert [row["provider"] for row in results] == list(settings)
    assert all(row["status"] == "disabled" for row in results)


def test_traffic_uses_readable_names_and_units():
    result = status_cli._initial_result("ssp", SourceConfig())
    result["measurements"] = [
        asdict(definition.create(size))
        for definition, size in zip(
            TRAFFIC_METRICS.values(), (1024, 1048576, 1073741824), strict=True
        )
    ]
    output = StringIO()
    Console(file=output, width=180).print(status_cli._render_table([result]))
    text = output.getvalue()
    assert "Traffic upload: 1.00 KiB" in text
    assert "Traffic download: 1.00 MiB" in text
    assert "Traffic deducted: 1.00 GiB" in text
    assert "kazu_subscription_traffic" not in text
    assert result["measurements"][0]["value"] == 1024
