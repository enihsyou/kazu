"""One-shot, concurrent usage queries rendered as a terminal table or JSON."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from kazu.clicmds.base import CLICommand
from kazu.clicmds.documentation import DocumentationAction
from kazu.clicmds.ssp_display import SSPConsole, _format_bytes
from kazu.config import AppConfig, SourceConfig, load_config
from kazu.exitcodes import EXIT_FAILURE, EXIT_SUCCESS
from kazu.lib.measurements import (
    CALLS_USED,
    CREDITS_CAP,
    CREDITS_REMAINING,
    CREDITS_USED,
    LLM_QUOTA_REMAINING_RATIO,
    LLM_QUOTA_RESET,
    MONEY_REMAINING,
    TRAFFIC_METRICS,
)
from kazu.lib.usage import CollectionError
from kazu.sources.registry import create_source, source_configs


def _initial_result(name: str, settings: SourceConfig) -> dict[str, Any]:
    return {
        "provider": name,
        "enabled": settings.enabled,
        "source": settings.source,
        "interval": settings.interval,
        "status": "loading" if settings.enabled else "disabled",
        "measurements": [],
        "duration_seconds": None,
    }


def _query(name: str, config: AppConfig, settings: SourceConfig) -> dict[str, Any]:
    result = _initial_result(name, settings)
    if not settings.enabled:
        return result
    source = create_source(name, config)
    started = monotonic()
    try:
        snapshot = source.collect()
        result.update(
            source=source.mode,
            status="partial" if snapshot.warnings else "ok",
            observed_at=snapshot.observed_at,
            warnings=list(snapshot.warnings),
            measurements=[asdict(value) for value in snapshot.measurements],
        )
    except Exception as exc:
        detail = str(exc) if isinstance(exc, CollectionError) else type(exc).__name__
        result.update(status="error", error=detail)
    finally:
        result["duration_seconds"] = monotonic() - started
        source.close()
    return result


def _render_table(results: list[dict[str, Any]]) -> Table:
    table = Table(header_style="bold", title="Kazu Status")
    table.add_column("Provider", style="bold cyan")
    table.add_column("Source")
    table.add_column("Interval", justify="right", style="dim")
    table.add_column("Duration", justify="right")
    table.add_column("Status")
    table.add_column("Current values")
    status_styles = {
        "ok": "green",
        "partial": "yellow",
        "error": "red",
        "disabled": "dim",
        "loading": "yellow",
    }
    categories = {
        MONEY_REMAINING.name: ("Money remaining", "green"),
        CREDITS_REMAINING.name: ("Credits remaining", "magenta"),
        CREDITS_CAP.name: ("Credits cap", "magenta"),
        CREDITS_USED.name: ("Credits used", "magenta"),
        CALLS_USED.name: ("Calls used", "cyan"),
        LLM_QUOTA_REMAINING_RATIO.name: ("Quota remaining", "magenta"),
        LLM_QUOTA_RESET.name: ("Quota resets", "cyan"),
        TRAFFIC_METRICS["upload"].name: ("Traffic upload", "magenta"),
        TRAFFIC_METRICS["download"].name: ("Traffic download", "blue"),
        TRAFFIC_METRICS["deducted"].name: ("Traffic deducted", "cyan"),
    }
    for result in results:
        values = Text()
        for value in result["measurements"]:
            labels = ", ".join(f"{k}={v}" for k, v in value["labels"])
            label_text = f" ({labels})" if labels else ""
            label, style = categories.get(value["name"], (value["name"], "default"))
            formatted = f"{value['value']:g}"
            if value["name"] in {definition.name for definition in TRAFFIC_METRICS.values()}:
                formatted = _format_bytes(value["value"])
            elif value["name"] == LLM_QUOTA_REMAINING_RATIO.name:
                formatted = f"{value['value']:.1%}"
            elif value["name"] == LLM_QUOTA_RESET.name:
                formatted = (
                    datetime.fromtimestamp(value["value"])
                    .astimezone()
                    .isoformat(timespec="seconds")
                )
            values.append(f"{label}{label_text}: {formatted}\n", style=style)
        for warning in result.get("warnings", []):
            values.append(f"{warning}\n", style="yellow")
        if "error" in result:
            values.append(result["error"], style="red")
        values.rstrip()
        duration = result["duration_seconds"]
        table.add_row(
            result["provider"],
            result["source"],
            f"{result['interval']:g}s",
            "—" if duration is None else f"{duration:.3f}s",
            Text(result["status"], style=status_styles[result["status"]]),
            values,
        )
    return table


class StatusCommand(
    CLICommand, name="status", help="Query current source usage and display status"
):
    def register_parser(self, subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--config", type=Path, help="Path to config.toml")
        subparser.add_argument("--json", action="store_true", help="Output JSON instead of a table")
        subparser.add_argument("--docs", action=DocumentationAction)
        subparser.set_defaults(func=self._run)

    def _run(self, args: argparse.Namespace) -> int:
        config = load_config(args.config)
        SSPConsole(stderr=True).configure_logging()
        settings_by_name = source_configs(config)
        results = [_initial_result(name, settings) for name, settings in settings_by_name.items()]
        console = Console(markup=False)
        interactive = console.is_terminal and not args.json
        display = (
            Live(_render_table(results), console=console, auto_refresh=False)
            if interactive
            else nullcontext()
        )
        with display as live, ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(_query, name, config, settings): index
                for index, (name, settings) in enumerate(settings_by_name.items())
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
                if live is not None:
                    live.update(_render_table(results), refresh=True)
        if args.json:
            print(json.dumps(results, indent=2))
        elif not interactive:
            console.print(_render_table(results))
        return (
            EXIT_FAILURE
            if any(r["status"] in {"error", "partial"} for r in results)
            else EXIT_SUCCESS
        )
