from __future__ import annotations

import argparse
import inspect
from abc import ABC, abstractmethod
from typing import ClassVar


class CLICommand(ABC):
    """Define the parser registration contract for a CLI command."""

    name: ClassVar[str]
    """ Name of the command, used as the subcommand name in the CLI. """
    help: ClassVar[str]
    """ Short description of the command, used in the CLI help message. """

    _registry: ClassVar[dict[str, type[CLICommand]]] = {}

    def __init_subclass__(cls, *, name: str, help: str, register=True, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return

        if not name.strip():
            raise ValueError(f"CLI command {cls.__name__} must define non-empty 'name'")
        if not help.strip():
            raise ValueError(f"CLI command {cls.__name__} must define non-empty 'help'")
        command_name = name.strip()
        if command_name in CLICommand._registry:
            raise ValueError(f"Duplicate CLI command name: {command_name}")

        cls.name = command_name
        cls.help = help.strip()
        if register:
            CLICommand._registry[command_name] = cls

    @classmethod
    def create_all(cls) -> list[CLICommand]:
        """Instantiate every registered concrete CLI command."""
        return [plugin_cls() for plugin_cls in cls._registry.values()]

    @abstractmethod
    def register_parser(self, subparser: argparse.ArgumentParser) -> None:
        """Register this command's arguments and handlers on a subparser."""
        raise NotImplementedError
