from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from kazu.config import InfluxDB3Config, get_config_path, load_config
from kazu.exitcodes import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE
from kazu.lib.clidocs import render_documentation
from kazu.lib.sspgateway import (
    GatewayTrace,
    SSPGateway,
    SSPGatewayError,
    TrafficLogResult,
    TrafficRecord,
)
from kazu.sources.base import SourcePlugin

_DOCUMENTATION_PATH = Path(__file__).resolve().parents[2] / "docs" / "cli" / "ssp.md"
_PROVIDER = "ssp"
_INFLUX_TABLE = "subscription_traffic_daily"
_METRIC_DESCRIPTIONS = {
    "proxy_traffic_upload_bytes": (
        "Current business-day cumulative SSP subscription upload traffic in bytes."
    ),
    "proxy_traffic_download_bytes": (
        "Current business-day cumulative SSP subscription download traffic in bytes."
    ),
    "proxy_traffic_deducted_bytes": (
        "Current business-day cumulative SSP subscription deducted traffic in bytes."
    ),
}


@dataclass(frozen=True)
class SSPTrafficReport:
    domain: str
    account: str
    extracted_at: datetime
    records: tuple[TrafficRecord, ...]


@dataclass(frozen=True)
class SubscriptionTrafficUsage:
    provider: str
    user_id: str
    usage_date: date
    server_rate: str
    upload_bytes: int
    download_bytes: int
    deducted_bytes: int


class InfluxDB3WriteError(RuntimeError):
    """InfluxDB 3 configuration, query, or write failure."""


class InfluxDB3DailyWriter:
    def __init__(self, config: InfluxDB3Config) -> None:
        missing = [
            name
            for name, value in (
                ("host", config.host),
                ("database", config.database),
                ("token", config.token),
            )
            if not value.strip()
        ]
        if missing:
            names = ", ".join(f"influxdb3.{name}" for name in missing)
            raise InfluxDB3WriteError(f"InfluxDB 3 configuration is incomplete: {names}")

        self._database = config.database.strip()
        self._base_url = config.host.strip().rstrip("/")
        self._client = httpx.Client(
            timeout=config.timeout,
            headers={"Authorization": f"Bearer {config.token.strip()}"},
        )

    def __enter__(self) -> InfluxDB3DailyWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def write_usages(self, usages: tuple[SubscriptionTrafficUsage, ...], today: date) -> int:
        if not usages:
            return 0

        table_exists = self._table_exists()
        pending: list[SubscriptionTrafficUsage] = []
        for usage in usages:
            if usage.usage_date == today:
                pending.append(usage)
                continue
            existing = self._existing_usage(usage) if table_exists else None
            if existing is None:
                pending.append(usage)
            elif existing != usage:
                raise InfluxDB3WriteError(
                    "InfluxDB 3 already contains a different daily final for "
                    f"provider={usage.provider}, user_id={usage.user_id}, "
                    f"usage_date={usage.usage_date.isoformat()}"
                )

        if not pending:
            return 0

        response = self._client.post(
            f"{self._base_url}/api/v3/write_lp",
            params={
                "db": self._database,
                "precision": "ns",
                "accept_partial": "false",
            },
            content="\n".join(_influx_line(usage, today) for usage in pending),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        self._raise_for_status(response, "write daily traffic")
        return len(pending)

    def _table_exists(self) -> bool:
        rows = self._query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'iox' AND table_name = $table_name",
            {"table_name": _INFLUX_TABLE},
        )
        return bool(rows)

    def _existing_usage(
        self, expected: SubscriptionTrafficUsage
    ) -> SubscriptionTrafficUsage | None:
        rows = self._query(
            f'SELECT upload_bytes, download_bytes, deducted_bytes, server_rate, usage_date '
            f'FROM "{_INFLUX_TABLE}" '
            "WHERE provider = $provider AND user_id = $user_id "
            "AND usage_date = $usage_date LIMIT 2",
            {
                "provider": expected.provider,
                "user_id": expected.user_id,
                "usage_date": expected.usage_date.isoformat(),
            },
        )
        if not rows:
            return None
        if len(rows) > 1:
            raise InfluxDB3WriteError(
                "InfluxDB 3 contains multiple daily finals for "
                f"provider={expected.provider}, user_id={expected.user_id}, "
                f"usage_date={expected.usage_date.isoformat()}"
            )
        row = rows[0]
        try:
            return SubscriptionTrafficUsage(
                provider=expected.provider,
                user_id=expected.user_id,
                usage_date=date.fromisoformat(str(row["usage_date"])),
                server_rate=_influx_string(row["server_rate"]),
                upload_bytes=_influx_integer(row["upload_bytes"]),
                download_bytes=_influx_integer(row["download_bytes"]),
                deducted_bytes=_influx_integer(row["deducted_bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InfluxDB3WriteError(
                "InfluxDB 3 returned an invalid subscription_traffic_daily row"
            ) from exc

    def _query(self, query: str, params: dict[str, str]) -> list[dict[str, Any]]:
        response = self._client.post(
            f"{self._base_url}/api/v3/query_sql",
            json={
                "db": self._database,
                "q": query,
                "params": params,
                "format": "json",
            },
        )
        self._raise_for_status(response, "query daily traffic")
        try:
            payload = response.json()
        except ValueError as exc:
            raise InfluxDB3WriteError("InfluxDB 3 query returned invalid JSON") from exc
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise InfluxDB3WriteError("InfluxDB 3 query returned an unexpected response")
        return payload

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InfluxDB3WriteError(
                f"Unable to {action} in InfluxDB 3: HTTP {response.status_code}"
            ) from exc


class _SSPHelpAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del namespace, values, option_string
        render_documentation(_DOCUMENTATION_PATH)
        parser.exit(EXIT_SUCCESS)


class SSPSource(SourcePlugin):
    name = "ssp"
    help = "Fetch SSP traffic statistics through the encrypted API gateway"

    def __init__(self) -> None:
        self._parser: argparse.ArgumentParser | None = None

    def register_parser(
        self, subparsers: argparse._SubParsersAction[argparse.ArgumentParser]
    ) -> None:
        cfg = load_config().ssp
        parser = subparsers.add_parser(self.name, help=self.help, description=self.help)
        self._parser = parser
        parser.set_defaults(func=self._show_help)
        parser.add_argument(
            "--docs",
            action=_SSPHelpAction,
            nargs=0,
            help="Show the full SSP usage documentation",
        )

        command_parsers = parser.add_subparsers()
        get_parser = command_parsers.add_parser(
            "get",
            help="Fetch and display SSP traffic statistics",
            description="Fetch and display SSP traffic statistics in a terminal table.",
        )
        get_parser.set_defaults(func=self._run_get)
        _add_gateway_arguments(get_parser, cfg.timeout)
        metrics_parser = command_parsers.add_parser(
            "metrics",
            help="Export current traffic in Prometheus text format",
            description=(
                "Export today's SSP traffic as Prometheus text format and optionally persist "
                "daily traffic records to InfluxDB 3."
            ),
        )
        metrics_parser.set_defaults(func=self._run_metrics)
        _add_gateway_arguments(metrics_parser, cfg.timeout)
        metrics_parser.add_argument(
            "--output",
            type=Path,
            help="Atomically replace this textfile collector output instead of writing stdout",
        )
        metrics_parser.add_argument(
            "--push-influxdb",
            action="store_true",
            help="Persist daily traffic records to the configured InfluxDB 3 server",
        )

    def _show_help(self, args: argparse.Namespace) -> int:
        del args
        if self._parser is not None:
            self._parser.print_help()
        return EXIT_SUCCESS

    def _run_get(self, args: argparse.Namespace) -> int:
        console = Console()
        traffic = _fetch_traffic(args, console)
        if traffic is None:
            return EXIT_FAILURE if _authorization(args) else EXIT_USAGE

        cfg = load_config().ssp
        report = SSPTrafficReport(
            domain=cfg.domain or "ssp",
            account=_account_label(traffic),
            extracted_at=datetime.now(tz=UTC),
            records=traffic.records,
        )
        render_ssp_output(console, report)
        return EXIT_SUCCESS

    def _run_metrics(self, args: argparse.Namespace) -> int:
        console = Console()
        error_console = Console(stderr=True)
        trace_console = error_console if args.verbose else console
        traffic = _fetch_traffic(args, trace_console, error_console=error_console)
        if traffic is None:
            return EXIT_FAILURE if _authorization(args) else EXIT_USAGE

        today = _local_now().date()
        try:
            usages = _build_daily_usages(traffic.records, today)
        except ValueError as exc:
            error_console.print(f"[bold red]Unable to export SSP traffic:[/bold red] {exc}")
            return EXIT_FAILURE

        current = tuple(usage for usage in usages if usage.usage_date == today)
        metrics_error = _export_metrics(current, args.output, console, error_console)
        influx_error = self._push_influxdb(args, usages, today, error_console)
        return EXIT_FAILURE if metrics_error or influx_error else EXIT_SUCCESS

    @staticmethod
    def _push_influxdb(
        args: argparse.Namespace,
        usages: tuple[SubscriptionTrafficUsage, ...],
        today: date,
        error_console: Console,
    ) -> bool:
        if not args.push_influxdb:
            return False
        try:
            with InfluxDB3DailyWriter(load_config().influxdb3) as writer:
                writer.write_usages(usages, today)
        except (InfluxDB3WriteError, httpx.HTTPError, OSError, ValueError) as exc:
            error_console.print(f"[bold red]Unable to persist SSP traffic:[/bold red] {exc}")
            return True
        return False


def _add_gateway_arguments(parser: argparse.ArgumentParser, timeout: float) -> None:
    parser.add_argument(
        "--authorization",
        default=None,
        help="Complete Bearer authorization value (overrides config)",
    )
    parser.add_argument(
        "--timeout", type=float, default=timeout, help="Request timeout in seconds"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show redacted HTTP request and response transcripts",
    )


def _authorization(args: argparse.Namespace) -> str:
    configured = load_config().ssp.authorization
    value = args.authorization if args.authorization is not None else configured
    return value.strip()


def _fetch_traffic(
    args: argparse.Namespace,
    trace_console: Console,
    *,
    error_console: Console | None = None,
) -> TrafficLogResult | None:
    cfg = load_config().ssp
    authorization = _authorization(args)
    errors = error_console or trace_console
    if not authorization:
        errors.print("[bold red]SSP Authorization is required.[/bold red]")
        errors.print(
            "Pass [cyan]--authorization[/cyan] or set "
            f"[cyan]sources.ssp.authorization[/cyan] in [cyan]{get_config_path()}[/cyan]. "
            "Use a complete value such as [cyan]Bearer <credential>[/cyan]."
        )
        return None

    trace = (lambda item: render_gateway_trace(trace_console, item)) if args.verbose else None
    try:
        with SSPGateway(
            authorization,
            api_base_url=cfg.api_base_url,
            traffic_endpoint=cfg.traffic_endpoint,
            gateway_endpoints=cfg.gateway_endpoints,
            timeout=args.timeout,
            trace=trace,
        ) as client:
            return client.get_traffic_log()
    except (SSPGatewayError, ValueError) as exc:
        errors.print(f"[bold red]Unable to fetch SSP traffic:[/bold red] {exc}")
        return None


def _build_daily_usages(
    records: tuple[TrafficRecord, ...], today: date
) -> tuple[SubscriptionTrafficUsage, ...]:
    usages: dict[tuple[str, date], SubscriptionTrafficUsage] = {}
    for record in records:
        usage = _daily_usage(record)
        if usage.usage_date > today:
            raise ValueError(
                f"SSP returned a future usage date: {usage.usage_date.isoformat()}"
            )
        key = (usage.user_id, usage.usage_date)
        existing = usages.get(key)
        if existing is not None and existing != usage:
            raise ValueError(
                "SSP returned conflicting traffic records for "
                f"user_id={usage.user_id}, usage_date={usage.usage_date.isoformat()}"
            )
        usages[key] = usage
    return tuple(sorted(usages.values(), key=lambda item: (item.usage_date, item.user_id)))


def _daily_usage(record: TrafficRecord) -> SubscriptionTrafficUsage:
    user_id = str(record.user_id).strip()
    if "\n" in user_id or "\r" in user_id:
        raise ValueError("SSP traffic record contains an invalid user_id")

    values = {
        "upload": record.upload_bytes,
        "download": record.download_bytes,
    }
    for name, value in values.items():
        if value < 0:
            raise ValueError(f"SSP traffic record contains negative {name} bytes")
    if not record.multiplier.is_finite() or record.multiplier < 0:
        raise ValueError("SSP traffic record contains an invalid server_rate")

    total = record.upload_bytes + record.download_bytes
    deducted = int(
        (Decimal(total) * record.multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return SubscriptionTrafficUsage(
        provider=_PROVIDER,
        user_id=user_id,
        usage_date=record.recorded_at.astimezone().date(),
        server_rate=_server_rate_text(record),
        upload_bytes=record.upload_bytes,
        download_bytes=record.download_bytes,
        deducted_bytes=deducted,
    )


def _server_rate_text(record: TrafficRecord) -> str:
    raw_value = record.raw.get("server_rate")
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip()
    return format(record.multiplier, "f")


def _export_metrics(
    current: tuple[SubscriptionTrafficUsage, ...],
    output: Path | None,
    console: Console,
    error_console: Console,
) -> bool:
    if not current:
        error_console.print(
            "[bold red]Unable to export SSP traffic:[/bold red] "
            "SSP returned no record for today's local business date; "
            "an existing metrics file was left unchanged."
        )
        return True

    content = _prometheus_text(current)
    if output is None:
        console.file.write(content)
        console.file.flush()
        return False

    try:
        _atomic_write(output, content)
    except OSError as exc:
        error_console.print(f"[bold red]Unable to write SSP metrics:[/bold red] {exc}")
        return True
    return False


def _prometheus_text(usages: tuple[SubscriptionTrafficUsage, ...]) -> str:
    values = {
        "proxy_traffic_upload_bytes": "upload_bytes",
        "proxy_traffic_download_bytes": "download_bytes",
        "proxy_traffic_deducted_bytes": "deducted_bytes",
    }
    lines: list[str] = []
    for metric_name, attribute in values.items():
        lines.extend(
            (
                f"# HELP {metric_name} {_METRIC_DESCRIPTIONS[metric_name]}",
                f"# TYPE {metric_name} gauge",
            )
        )
        for usage in sorted(usages, key=lambda item: item.user_id):
            labels = (
                f'provider="{_prometheus_label(usage.provider)}",'
                f'user_id="{_prometheus_label(usage.user_id)}",'
                f'server_rate="{_prometheus_label(usage.server_rate)}"'
            )
            lines.append(f"{metric_name}{{{labels}}} {getattr(usage, attribute)}")
    return "\n".join(lines) + "\n"


def _prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _atomic_write(output: Path, content: str) -> None:
    destination = output.expanduser().resolve()
    parent = destination.parent
    if not parent.is_dir():
        raise OSError(f"output directory does not exist: {parent}")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=parent,
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
        temporary_path = None
        os.utime(destination, None)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _influx_line(usage: SubscriptionTrafficUsage, today: date) -> str:
    tags = (
        f"provider={_influx_tag(usage.provider)},user_id={_influx_tag(usage.user_id)}"
    )
    fields = (
        f"upload_bytes={usage.upload_bytes}u,"
        f"download_bytes={usage.download_bytes}u,"
        f"deducted_bytes={usage.deducted_bytes}u,"
        f'server_rate="{_influx_field_string(usage.server_rate)}",'
        f'usage_date="{_influx_field_string(usage.usage_date.isoformat())}"'
    )
    timestamp = _influx_timestamp(usage.usage_date, today)
    return f"{_INFLUX_TABLE},{tags} {fields} {timestamp}"


def _influx_timestamp(usage_date: date, today: date) -> int:
    if usage_date == today:
        now = _local_now()
        return int(now.timestamp()) * 1_000_000_000 + now.microsecond * 1_000
    final_second = datetime.combine(usage_date, time(23, 59, 59)).astimezone()
    return int(final_second.timestamp()) * 1_000_000_000


def _influx_tag(value: str) -> str:
    return value.replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def _influx_field_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _influx_integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer field")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdecimal():
        result = int(value)
    else:
        raise ValueError("invalid integer field")
    if result < 0:
        raise ValueError("negative integer field")
    return result


def _influx_string(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid string field")
    return value


def _account_label(traffic: TrafficLogResult) -> str:
    return f"user:{traffic.records[0].user_id}" if traffic.records else "unknown"


def _local_now() -> datetime:
    return datetime.now().astimezone()


def render_gateway_trace(console: Console, trace: GatewayTrace) -> None:
    console.print(Syntax(trace.request_http, "http", theme="ansi_dark", word_wrap=True))
    console.print(Syntax(trace.response_http, "http", theme="ansi_dark", word_wrap=True))


def render_ssp_output(console: Console, report: SSPTrafficReport) -> None:
    summary = (
        "source: ssp-traffic\n"
        f"domain: {report.domain}\n"
        f"account: {report.account}\n"
        f"rows: {len(report.records)}\n"
        f"extracted_at: {report.extracted_at.astimezone().isoformat()}"
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


def _format_datetime(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d")


def _format_multiplier(value: Decimal) -> str:
    return f"{value:f}x"


def _format_bytes(value: int | Decimal) -> str:
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
