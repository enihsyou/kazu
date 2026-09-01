from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from kazu.config import get_config_path, load_config
from kazu.lib.sspgateway import (
    GatewayTrace,
    SSPGateway,
    SSPGatewayError,
    TrafficLogResult,
    TrafficRecord,
)
from kazu.sources.base import SourcePlugin

_DOCUMENTATION_PATH = Path(__file__).resolve().parents[2] / "docs" / "cli" / "ssp.md"


@dataclass(frozen=True)
class SSPTrafficReport:
    domain: str
    account: str
    extracted_at: datetime
    records: tuple[TrafficRecord, ...]


class _SSPHelpAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del namespace, values, option_string
        Console().print(Markdown(_load_documentation()))
        parser.exit()


class SSPSource(SourcePlugin):
    name = "ssp"
    help = "Fetch SSP traffic statistics through the encrypted API gateway"

    def register_parser(
        self, subparsers: argparse._SubParsersAction[argparse.ArgumentParser]
    ) -> None:
        cfg = load_config().ssp
        parser = subparsers.add_parser(self.name, add_help=False, help=self.help)
        parser.add_argument(
            "-h",
            "--help",
            action=_SSPHelpAction,
            nargs=0,
            help="Show SSP usage documentation",
        )
        parser.add_argument(
            "--authorization",
            default=None,
            help="Complete Bearer authorization value (overrides config)",
        )
        parser.add_argument(
            "--timeout", type=float, default=cfg.timeout, help="Request timeout in seconds"
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show redacted HTTP request and response transcripts",
        )

    def run(self, args: argparse.Namespace, console: Console) -> int:
        cfg = load_config().ssp
        authorization = (
            args.authorization if args.authorization is not None else cfg.authorization
        ).strip()
        if not authorization:
            console.print("[bold red]SSP Authorization is required.[/bold red]")
            console.print(
                "Pass [cyan]--authorization[/cyan] or set "
                f"[cyan]sources.ssp.authorization[/cyan] in [cyan]{get_config_path()}[/cyan]. "
                "Use a complete value such as [cyan]Bearer <credential>[/cyan]."
            )
            return 2

        trace = (lambda item: render_gateway_trace(console, item)) if args.verbose else None
        try:
            with SSPGateway(
                authorization,
                api_base_url=cfg.api_base_url,
                traffic_endpoint=cfg.traffic_endpoint,
                gateway_endpoints=cfg.gateway_endpoints,
                timeout=args.timeout,
                trace=trace,
            ) as client:
                traffic = client.get_traffic_log()
        except (SSPGatewayError, ValueError) as exc:
            console.print(f"[bold red]Unable to fetch SSP traffic:[/bold red] {exc}")
            return 1

        report = SSPTrafficReport(
            domain=cfg.domain or "ssp",
            account=_account_label(traffic),
            extracted_at=datetime.now(tz=UTC),
            records=traffic.records,
        )
        render_ssp_output(console, report)
        return 0


def _account_label(traffic: TrafficLogResult) -> str:
    for record in traffic.records:
        if record.user_id is not None:
            return f"user:{record.user_id}"
    return "unknown"


def _load_documentation() -> str:
    try:
        return _DOCUMENTATION_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Unable to load SSP documentation: {_DOCUMENTATION_PATH}") from exc


def render_gateway_trace(console: Console, trace: GatewayTrace) -> None:
    console.print(Syntax(trace.request_http, "http", theme="ansi_dark", word_wrap=True))
    console.print(Syntax(trace.response_http, "http", theme="ansi_dark", word_wrap=True))


def render_ssp_output(console: Console, report: SSPTrafficReport) -> None:
    summary = (
        "source: ssp-traffic\n"
        f"domain: {report.domain}\n"
        f"account: {report.account}\n"
        f"rows: {len(report.records)}\n"
        f"extracted_at: {report.extracted_at.isoformat()}"
    )
    console.print(Panel.fit(summary, title="SSP Traffic Summary", border_style="cyan"))

    table = Table(title="SSP Traffic Details", header_style="bold green")
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Upload", style="magenta", no_wrap=True)
    table.add_column("Download", style="blue", no_wrap=True)
    table.add_column("Multiplier", style="yellow", no_wrap=True)
    table.add_column("Total", style="bold", no_wrap=True)

    for record in report.records:
        table.add_row(
            _format_datetime(record.recorded_at),
            _format_bytes(record.upload_bytes),
            _format_bytes(record.download_bytes),
            _format_multiplier(record.multiplier),
            _format_bytes(record.billed_bytes),
        )
    console.print(table)


def _format_datetime(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z") if value is not None else ""


def _format_multiplier(value: Decimal | None) -> str:
    return f"{value:f}x" if value is not None else ""


def _format_bytes(value: int | Decimal | None) -> str:
    if value is None:
        return ""
    size = Decimal(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if abs(size) < 1024 or candidate == units[-1]:
            break
        size /= 1024
    if unit == "B" and size == size.to_integral():
        return f"{int(size)} {unit}"
    return f"{size.quantize(Decimal('0.01'))} {unit}"
