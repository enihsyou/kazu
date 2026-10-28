"""Assemble the multi-source exporter and its background workers."""

from __future__ import annotations

import argparse
import logging
from contextlib import ExitStack
from pathlib import Path

from kazu.clicmds.base import CLICommand
from kazu.clicmds.documentation import DocumentationAction
from kazu.clicmds.ssp_display import SSPConsole
from kazu.config import load_config
from kazu.exitcodes import EXIT_SUCCESS
from kazu.lib.metrics.exporter import MetricsExporter
from kazu.lib.metrics.server import MetricsHTTPServer
from kazu.lib.metrics.watch import SourceWatch
from kazu.sources.registry import create_source, source_configs

_LOGGER = logging.getLogger(__name__)


class MetricsCommand(CLICommand, name="metrics", help="Serve usage metrics for Prometheus"):
    def register_parser(self, subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--config", type=Path, help="Path to config.toml")
        subparser.add_argument("--host", help="Override metrics.host")
        subparser.add_argument("--port", type=int, help="Override metrics.port")
        subparser.add_argument("--docs", action=DocumentationAction)
        subparser.set_defaults(func=self._run)

    def _run(self, args: argparse.Namespace) -> int:
        config = load_config(args.config)
        SSPConsole(stderr=True).configure_logging()
        watches = {
            name: SourceWatch(name, create_source(name, config), settings)
            for name, settings in source_configs(config).items()
            if settings.enabled
        }
        exporter = MetricsExporter(watches)
        try:
            with ExitStack() as resources:
                # Bind first so an occupied port never starts provider queries.
                server = resources.enter_context(
                    MetricsHTTPServer(
                        args.host if args.host is not None else config.metrics.host,
                        args.port if args.port is not None else config.metrics.port,
                        exporter.render,
                    )
                )
                for watch in watches.values():
                    watch.start()
                    resources.callback(watch.close)
                if not watches:
                    _LOGGER.warning("No sources enabled; set sources.<provider>.enabled = true.")
                _LOGGER.info("Serving metrics at %s (Ctrl+C to stop).", server.metrics_url)
                server.serve_forever()
        except KeyboardInterrupt:
            _LOGGER.info("Metrics server stopped.")
        return EXIT_SUCCESS
