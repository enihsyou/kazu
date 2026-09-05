from __future__ import annotations

import logging
from decimal import Decimal

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from kazu.config import get_config_path
from kazu.lib.sspgateway import GatewayTrace
from kazu.lib.traffic import SubscriptionTrafficSnapshot


class SSPConsole:
    """Terminal-only report, trace, and diagnostic presentation."""

    def __init__(self, *, stderr: bool = False) -> None:
        self.console = Console(stderr=stderr)
        """Store the Rich console used for terminal output."""

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
        accounts = ", ".join(sorted({usage.user_id for usage in snapshot.usages})) or "unknown"
        summary = (
            "source: ssp-traffic\n"
            f"gateway: {gateway}\n"
            f"account: user:{accounts}\n"
            f"rows: {len(snapshot.usages)}\n"
            f"extracted_at: {snapshot.observed_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.console.print(Panel.fit(summary, title="SSP Traffic Summary", border_style="cyan"))

        table = Table(title="SSP Traffic Details", header_style="bold green")
        table.add_column("Date", style="cyan", no_wrap=True)
        table.add_column("Upload", style="magenta", no_wrap=True, justify="right")
        table.add_column("Download", style="blue", no_wrap=True, justify="right")
        table.add_column("Multiplier", style="yellow", no_wrap=True)
        table.add_column("Total", style="bold", no_wrap=True, justify="right")
        for usage in snapshot.usages:
            table.add_row(
                usage.usage_date.isoformat(),
                _format_bytes(usage.upload_bytes, detail=detail),
                _format_bytes(usage.download_bytes, detail=detail),
                f"{usage.server_rate}x",
                _format_bytes(usage.deducted_bytes, detail=detail),
            )
        self.console.print(table)


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
