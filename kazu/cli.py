from __future__ import annotations

import argparse
import sys

from rich.console import Console

from kazu.config import APP_NAME
from kazu.sources import get_sources
from kazu.sources.base import SourcePlugin


def build_parser() -> tuple[argparse.ArgumentParser, dict[str, SourcePlugin]]:
    parser = argparse.ArgumentParser(
        prog=APP_NAME, description="Collect structured usage statistics from configured sources"
    )

    subparsers = parser.add_subparsers(dest="command")

    sources = get_sources()
    source_map: dict[str, SourcePlugin] = {}

    for source in sources:
        source.register_parser(subparsers)
        source_map[source.name] = source

    return parser, source_map


def main(argv: list[str] | None = None) -> int:
    parser, source_map = build_parser()

    arg_list = list(sys.argv[1:] if argv is None else argv)
    if not arg_list:
        parser.print_help()
        return 0

    args = parser.parse_args(arg_list)
    console = Console()

    source = source_map.get(args.command)
    if source is None:
        parser.print_help()
        return 1

    return source.run(args, console)


if __name__ == "__main__":
    raise SystemExit(main())
