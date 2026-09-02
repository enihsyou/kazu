from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import ClassVar


class SourcePlugin(ABC):
    name: ClassVar[str]
    help: ClassVar[str]
    _registry: ClassVar[dict[str, type[SourcePlugin]]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls is SourcePlugin:
            return
        if getattr(cls, "__abstractmethods__", False):
            return

        name = getattr(cls, "name", "").strip()
        if not name:
            raise ValueError(f"Source plugin {cls.__name__} must define non-empty 'name'")
        if name in SourcePlugin._registry:
            raise ValueError(f"Duplicate source plugin name: {name}")

        SourcePlugin._registry[name] = cls

    @classmethod
    def create_all(cls) -> list[SourcePlugin]:
        return [plugin_cls() for plugin_cls in cls._registry.values()]

    @abstractmethod
    def register_parser(
        self, subparsers: argparse._SubParsersAction[argparse.ArgumentParser]
    ) -> None:
        raise NotImplementedError
