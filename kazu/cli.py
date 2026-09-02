from __future__ import annotations

import argparse
import sys

from kazu.config import APP_NAME
from kazu.exitcodes import EXIT_SUCCESS
from kazu.sources import get_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME, description="Collect structured usage statistics from configured sources"
    )

    subparsers = parser.add_subparsers()

    for source in get_sources():
        source.register_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()

    arg_list = list(sys.argv[1:] if argv is None else argv)
    if not arg_list:
        parser.print_help()
        return EXIT_SUCCESS

    args = parser.parse_args(arg_list)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
