from __future__ import annotations

import argparse
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from remains.agent_browser import is_installed, parse_json_output, run_agent_browser
from remains.sources.base import SourcePlugin

DEFAULT_SSP_URL = "https://s1.thefew01.top/#/traffic"

SSP_EVAL_SCRIPT = """(() => {
  const rows = Array.from(document.querySelectorAll('table tbody tr')).map((tr, i) => {
    const cells = Array.from(tr.querySelectorAll('td')).map((td) => (td.textContent || '').trim());
    return {
      index: i + 1,
      date: cells[0] || null,
      actualUpload: cells[1] || null,
      actualDownload: cells[2] || null,
      billingMultiplier: cells[3] || null,
      total: cells[4] || null
    };
  });

  const accountNode = Array.from(document.querySelectorAll('span')).find((n) => /@/.test((n.textContent || '').trim()));

  return {
    source: 'ssp-traffic',
    extractedAt: new Date().toISOString(),
    title: document.title,
    url: location.href,
    account: accountNode ? accountNode.textContent.trim() : null,
    rowCount: rows.length,
    rows
  };
})()"""


class SSPSource(SourcePlugin):
    name = "ssp"
    help = "Fetch SSP traffic statistics"

    def register_parser(self, subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = subparsers.add_parser(self.name, help=self.help)
        parser.add_argument("--url", default=DEFAULT_SSP_URL, help="Traffic page URL")
        parser.add_argument("--session", default="ssp", help="agent-browser session id")
        parser.add_argument(
            "--max-retries",
            type=int,
            default=5,
            help="Retry times when table rows are empty after opening page",
        )

    def run(self, args: argparse.Namespace, console: Console) -> int:
        if not is_installed():
            console.print("[bold red]agent-browser is not installed or not in PATH[/bold red]")
            return 1

        shared_args: list[str] = []
        if args.session:
            shared_args.extend(["--session", args.session])

        open_result = run_agent_browser([*shared_args, "open", args.url])
        if open_result.returncode != 0:
            console.print("[bold red]Failed to open SSP page with agent-browser[/bold red]")
            if open_result.stderr.strip():
                console.print(open_result.stderr.strip())
            elif open_result.stdout.strip():
                console.print(open_result.stdout.strip())
            return 1

        payload: dict[str, Any] | None = None
        retries = max(1, args.max_retries)

        for attempt in range(retries):
            eval_result = run_agent_browser([*shared_args, "eval", SSP_EVAL_SCRIPT])
            if eval_result.returncode != 0:
                console.print("[bold red]Failed to evaluate SSP page script[/bold red]")
                if eval_result.stderr.strip():
                    console.print(eval_result.stderr.strip())
                elif eval_result.stdout.strip():
                    console.print(eval_result.stdout.strip())
                return 1

            try:
                payload = parse_json_output(eval_result.stdout)
            except ValueError as exc:
                console.print(f"[bold red]{exc}[/bold red]")
                return 1

            row_count = payload.get("rowCount", 0)
            if isinstance(row_count, int) and row_count > 0:
                break

            if attempt < retries - 1:
                run_agent_browser([*shared_args, "wait", "800"])

        if payload is None:
            console.print("[bold red]No payload returned from SSP source[/bold red]")
            return 1

        render_ssp_output(console, payload)
        return 0


def render_ssp_output(console: Console, payload: dict[str, Any]) -> None:
    source = payload.get("source", "ssp-traffic")
    account = payload.get("account", "unknown")
    extracted_at = payload.get("extractedAt", "unknown")
    row_count = payload.get("rowCount", 0)

    summary = (
        f"source: {source}\n"
        f"account: {account}\n"
        f"rows: {row_count}\n"
        f"extracted_at: {extracted_at}"
    )
    console.print(Panel.fit(summary, title="SSP Traffic Summary", border_style="cyan"))

    table = Table(title="SSP Traffic Details", header_style="bold green")
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Upload", style="magenta", no_wrap=True)
    table.add_column("Download", style="blue", no_wrap=True)
    table.add_column("Multiplier", style="yellow", no_wrap=True)
    table.add_column("Total", style="bold", no_wrap=True)

    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("payload.rows is not a list")

    for row in rows:
        if not isinstance(row, dict):
            continue
        table.add_row(
            str(row.get("date", "")),
            str(row.get("actualUpload", "")),
            str(row.get("actualDownload", "")),
            str(row.get("billingMultiplier", "")),
            str(row.get("total", "")),
        )

    console.print(table)
