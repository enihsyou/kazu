"""One-shot, concurrent usage queries rendered as a terminal table or JSON."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from time import monotonic
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from kazu.clicmds.base import CLICommand
from kazu.clicmds.documentation import DocumentationAction
from kazu.config import AppConfig, SourceConfig, load_config
from kazu.exitcodes import EXIT_FAILURE, EXIT_SUCCESS
from kazu.lib.measurements import (
    CALLS_USED,
    CREDITS_CAP,
    CREDITS_REMAINING,
    CREDITS_USED,
    MONEY_PENDING_DEBIT,
    MONEY_REMAINING,
    MONEY_USED,
)
from kazu.lib.usage import CollectionError
from kazu.sources.registry import create_source, source_configs


def _query(name: str, config: AppConfig, settings: SourceConfig) -> dict[str, Any]:
    result = {
        "provider": name,
        "enabled": settings.enabled,
        "source": settings.source,
        "interval": settings.interval,
        "status": "disabled",
        "measurements": [],
        "duration_seconds": None,
    }
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
        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(_query, name, config, settings)
                for name, settings in source_configs(config).items()
            ]
            results = [future.result() for future in futures]
        if args.json:
            print(json.dumps(results, indent=2))
        else:
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
            }
            categories = {
                MONEY_REMAINING.name: ("Money remaining", "green"),
                MONEY_USED.name: ("Money used", "green"),
                MONEY_PENDING_DEBIT.name: ("Money pending debit", "green"),
                CREDITS_REMAINING.name: ("Credits remaining", "magenta"),
                CREDITS_CAP.name: ("Credits cap", "magenta"),
                CREDITS_USED.name: ("Credits used", "magenta"),
                CALLS_USED.name: ("Calls used", "cyan"),
            }
            for result in results:
                values = Text()
                for value in result["measurements"]:
                    labels = ", ".join(f"{k}={v}" for k, v in value["labels"])
                    label_text = f" ({labels})" if labels else ""
                    label, style = categories.get(value["name"], (value["name"], "default"))
                    values.append(f"{label}{label_text}: {value['value']:g}\n", style=style)
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
            Console(markup=False).print(table)
        return (
            EXIT_FAILURE
            if any(r["status"] in {"error", "partial"} for r in results)
            else EXIT_SUCCESS
        )
