from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from kazu.config import get_config_path
from kazu.lib.sspgateway import GatewayTrace
from kazu.lib.traffic import SubscriptionTrafficSnapshot, SubscriptionTrafficUsage


@dataclass
class _ColumnWidths:
    value: int = 0
    delta: int = 0


@dataclass
class _TrafficWidths:
    upload: _ColumnWidths = field(default_factory=_ColumnWidths)
    download: _ColumnWidths = field(default_factory=_ColumnWidths)
    deducted: _ColumnWidths = field(default_factory=_ColumnWidths)


class SSPConsole:
    """Terminal-only report, trace, and diagnostic presentation."""

    def __init__(self, *, stderr: bool = False) -> None:
        self.console = Console(stderr=stderr)

    def configure_logging(self) -> None:
        """Configure terminal rendering or unwrapped logs for redirected output."""
        logger = logging.getLogger("kazu")
        if not logger.handlers:
            logger.addHandler(self._logging_handler())
        logger.setLevel(logging.INFO)
        logger.propagate = False

    def _logging_handler(self) -> logging.Handler:
        """Use Rich only when the output stream is an interactive terminal."""
        if self.console.is_terminal:
            return RichHandler(console=self.console, show_path=False, markup=False)
        handler = logging.StreamHandler(self.console.file)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        return handler

    def missing_authorization(self) -> None:
        """Display guidance for configuring the missing SSP authorization."""
        self.error("SSP Authorization is required.")
        self.console.print(
            f"Pass --authorization or set sources.ssp.authorization in {get_config_path()}. "
            "Use a complete value such as Bearer <credential>.",
            markup=False,
        )

    def error(self, message: str) -> None:
        """Display an error message in the terminal."""
        self.console.print(message, style="bold red", markup=False)

    def trace(self, trace: GatewayTrace) -> None:
        """Display redacted gateway request and response transcripts."""
        self.console.print(Syntax(trace.request_http, "http", theme="ansi_dark", word_wrap=True))
        self.console.print(Syntax(trace.response_http, "http", theme="ansi_dark", word_wrap=True))

    def report(
        self, snapshot: SubscriptionTrafficSnapshot, *, gateway: str, detail: bool = False
    ) -> None:
        """Display the collected traffic snapshot as a summary and table."""
        self.console.print(self._report(snapshot, gateway=gateway, detail=detail))

    def watch(
        self,
        snapshot: SubscriptionTrafficSnapshot,
        *,
        collect: Callable[[], SubscriptionTrafficSnapshot],
        interval: float,
        gateway: str,
        detail: bool = False,
    ) -> None:
        """Periodically collect traffic and refresh the report in place."""
        last_data_at = snapshot.observed_at
        widths = _TrafficWidths()
        report = self._report(
            snapshot,
            gateway=gateway,
            detail=detail,
            last_data_at=last_data_at,
            widths=widths,
        )
        with Live(report, console=self.console, refresh_per_second=4) as live:
            previous = snapshot
            while True:
                time.sleep(interval)
                snapshot = collect()
                if previous.usages != snapshot.usages:
                    last_data_at = snapshot.observed_at
                live.update(
                    self._report(
                        snapshot,
                        gateway=gateway,
                        detail=detail,
                        previous=previous,
                        last_data_at=last_data_at,
                        widths=widths,
                    ),
                    refresh=True,
                )
                previous = snapshot

    def _report(
        self,
        snapshot: SubscriptionTrafficSnapshot,
        *,
        gateway: str,
        detail: bool,
        previous: SubscriptionTrafficSnapshot | None = None,
        last_data_at: datetime | None = None,
        widths: _TrafficWidths | None = None,
    ) -> Group:
        """Build a summary and traffic table for printing or live refresh."""
        accounts = ", ".join(sorted({usage.user_id for usage in snapshot.usages})) or "unknown"
        summary = [
            "source: ssp-traffic",
            f"gateway: {gateway}",
            f"account: user:{accounts}",
            f"rows: {len(snapshot.usages)}",
            f"extracted_at: {_format_time(snapshot.observed_at)}",
        ]
        if last_data_at is not None:
            summary.append(f"last_data_at: {_format_time(last_data_at)}")
        table = self._traffic_table(snapshot, detail=detail, previous=previous, widths=widths)
        return Group(
            Panel.fit("\n".join(summary), title="SSP Traffic Summary", border_style="cyan"),
            table,
        )

    def _traffic_table(
        self,
        snapshot: SubscriptionTrafficSnapshot,
        *,
        detail: bool,
        previous: SubscriptionTrafficSnapshot | None,
        widths: _TrafficWidths | None,
    ) -> Table:
        """Build the traffic table, optionally comparing it with a previous snapshot."""
        table = Table(title="SSP Traffic Details", header_style="bold green")
        table.add_column("Date", style="cyan", no_wrap=True)
        table.add_column(Align.right("Upload"), style="magenta", no_wrap=True)
        table.add_column(Align.right("Download"), style="blue", no_wrap=True)
        table.add_column("Multiplier", style="yellow", no_wrap=True)
        table.add_column(Align.right("Total"), style="bold", no_wrap=True)
        previous_usages = (
            None
            if previous is None
            else {(usage.user_id, usage.usage_date): usage for usage in previous.usages}
        )
        upload_cells = _traffic_cells(
            snapshot,
            previous_usages,
            detail,
            lambda usage: usage.upload_bytes,
            None if widths is None else widths.upload,
        )
        download_cells = _traffic_cells(
            snapshot,
            previous_usages,
            detail,
            lambda usage: usage.download_bytes,
            None if widths is None else widths.download,
        )
        deducted_cells = _traffic_cells(
            snapshot,
            previous_usages,
            detail,
            lambda usage: usage.deducted_bytes,
            None if widths is None else widths.deducted,
        )
        for usage, upload, download, deducted in zip(
            snapshot.usages, upload_cells, download_cells, deducted_cells, strict=True
        ):
            table.add_row(
                usage.usage_date.isoformat(),
                upload,
                download,
                f"{usage.server_rate}x",
                deducted,
            )
        return table


def _traffic_cells(
    current: SubscriptionTrafficSnapshot,
    previous_usages: dict[tuple[str, date], SubscriptionTrafficUsage] | None,
    detail: bool,
    value_for: Callable[[SubscriptionTrafficUsage], int],
    widths: _ColumnWidths | None,
) -> list[Text]:
    values: list[tuple[str, str | None, str | None]] = []
    for usage in current.usages:
        value = value_for(usage)
        delta = None
        if previous_usages is not None:
            previous_usage = previous_usages.get((usage.user_id, usage.usage_date))
            previous_value = 0 if previous_usage is None else value_for(previous_usage)
            delta = value - previous_value
        delta_text = None if delta in (None, 0) else _format_delta_bytes(delta, detail=detail)
        delta_style = None
        if delta_text is not None:
            delta_style = "green" if usage.usage_date == current.today else "red"
        values.append((_format_bytes(value, detail=detail), delta_text, delta_style))

    value_width = max((len(value) for value, _, _ in values), default=0)
    delta_width = max((len(delta) for _, delta, _ in values if delta is not None), default=0)
    if widths is not None:
        widths.value = max(widths.value, value_width)
        widths.delta = max(widths.delta, delta_width)
        value_width = widths.value
        delta_width = widths.delta
    return [
        _aligned_traffic_cell(value, delta, style, value_width, delta_width)
        for value, delta, style in values
    ]


def _aligned_traffic_cell(
    value: str,
    delta: str | None,
    delta_style: str | None,
    value_width: int,
    delta_width: int,
) -> Text:
    cell = Text(value.rjust(value_width))
    if delta_width == 0:
        return cell
    cell.append(" ")
    cell.append((delta or "").ljust(delta_width), style=delta_style)
    return cell


def _format_delta_bytes(value: int | Decimal, *, detail: bool) -> str:
    return f"Δ{_format_bytes(value, detail=detail)}"


def _format_time(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _format_bytes(value: int | Decimal, *, detail: bool = False) -> str:
    size = Decimal(value)
    if detail:
        formatted = format(size, ",f")
        if size == size.to_integral():
            formatted = format(size.to_integral(), ",f")
        return f"{formatted} B"

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
