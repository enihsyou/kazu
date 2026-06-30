from __future__ import annotations

import importlib
import pkgutil

from remains.sources.base import SourcePlugin

__all__ = ["SourcePlugin", "discover_sources", "get_sources"]


def discover_sources() -> None:
	for module_info in pkgutil.iter_modules(__path__):
		name = module_info.name
		if name.startswith("_") or name in {"base"}:
			continue
		importlib.import_module(f"{__name__}.{name}")


def get_sources() -> list[SourcePlugin]:
	discover_sources()
	return SourcePlugin.create_all()
