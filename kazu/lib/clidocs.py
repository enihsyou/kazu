"""Helpers for loading and rendering CLI documentation."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

__all__ = ["load_documentation", "render_documentation"]


def load_documentation(path: Path) -> str:
    """Load a UTF-8 Markdown document from *path*."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Unable to load CLI documentation: {path}") from exc


def render_documentation(path: Path, console: Console | None = None) -> None:
    """Render a Markdown CLI document to *console*."""
    (console or Console()).print(Markdown(load_documentation(path)))
