from __future__ import annotations

import argparse
import sys

from kazu.clicmds import get_commands
from kazu.config import APP_NAME
from kazu.exitcodes import EXIT_SUCCESS


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for kazu."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Collect structured usage statistics from configured sources",
    )

    subparsers = parser.add_subparsers(title="commands")
    for command in get_commands():
        subparser = subparsers.add_parser(command.name, help=command.help, description=command.help)
        command.register_parser(subparser)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run kazu with the supplied or process command-line arguments."""
    parser = build_parser()

    arg_list = list(sys.argv[1:] if argv is None else argv)
    if not arg_list:
        parser.print_help()
        return EXIT_SUCCESS

    args = parser.parse_args(arg_list)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
