"""CLI documentation loading and terminal rendering."""

from __future__ import annotations

import argparse
from importlib import resources
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from kazu.exitcodes import EXIT_FAILURE, EXIT_SUCCESS


class DocumentationAction(argparse.Action):
    """Render a command's packaged documentation and exit without running it."""

    def __init__(self, **kwargs) -> None:
        super().__init__(nargs=0, default=argparse.SUPPRESS, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del namespace, values, option_string
        command = parser.prog.split()[-1]
        try:
            CLIDocumentation(command).render()
        except RuntimeError as exc:
            parser.exit(EXIT_FAILURE, f"{exc}\n")
        parser.exit(EXIT_SUCCESS)


class CLIDocumentation:
    """Load and render packaged documentation for a CLI command."""

    def __init__(self, command: str) -> None:
        self._filename = f"{command}.md"

    def load(self) -> str:
        """Load the Markdown documentation for this command."""
        packaged = resources.files("kazu").joinpath("_docs", "cli", self._filename)
        try:
            if packaged.is_file():
                return packaged.read_text(encoding="utf-8")
            # Editable/source checkouts keep a single canonical copy under docs/.
            source = Path(__file__).resolve().parents[2] / "docs" / "cli" / self._filename
            return source.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Unable to load CLI documentation: {self._filename}") from exc

    def render(self, console: Console | None = None) -> None:
        """Render this command's documentation in the terminal."""
        (console or Console()).print(Markdown(self.load()))
