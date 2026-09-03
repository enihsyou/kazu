"""CLI command discovery; data sources do not register command-line parsers."""

from __future__ import annotations

import importlib
import pkgutil

from kazu.clicmds.base import CLICommand

__all__ = ["CLICommand", "get_commands"]


def discover_commands() -> None:
    """Discover and import all CLI command modules in this package."""
    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        if name.endswith("_cli"):
            importlib.import_module(f"{__name__}.{name}")


def get_commands() -> list[CLICommand]:
    """Return all CLI commands registered by this package."""
    discover_commands()
    return CLICommand.create_all()
