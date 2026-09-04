"""SSP CLI commands and service lifecycle wiring."""

from __future__ import annotations

import argparse
import logging
import math
from contextlib import ExitStack

from prometheus_client import CollectorRegistry, Gauge

from kazu.clicmds.base import CLICommand
from kazu.clicmds.documentation import DocumentationAction
from kazu.clicmds.ssp_display import SSPConsole
from kazu.config import AppConfig, SSPConfig, load_config
from kazu.exitcodes import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE
from kazu.lib.influxdb3.reporter import InfluxDB3Reporter
from kazu.lib.metrics.exporter import TrafficExporter
from kazu.lib.metrics.server import MetricsHTTPServer
from kazu.lib.sspgateway import SSPGatewayError
from kazu.lib.traffic import TrafficCollectionError, TrafficSnapshot
from kazu.sources.ssp import SSPSource

_LOGGER = logging.getLogger(__name__)


class SSPCommand(
    CLICommand,
    name="ssp",
    help="Fetch SSP traffic statistics through the encrypted API gateway",
):
    """Register commands for fetching and serving SSP traffic statistics."""

    def __init__(self) -> None:
        """Initialize the SSP command registration state."""
        self._parser: argparse.ArgumentParser | None = None

    def register_parser(self, subparser: argparse.ArgumentParser) -> None:
        """Register SSP retrieval and metrics subcommands."""
        config = load_config().ssp
        self._parser = subparser
        subparser.set_defaults(func=self._show_help)
        subparser.add_argument(
            "--docs",
            action=DocumentationAction,
            help="Show the full SSP usage documentation",
        )

        commands = subparser.add_subparsers()
        get_parser = commands.add_parser(
            "get",
            help="Fetch and display SSP traffic statistics",
            description="Fetch and display SSP traffic statistics in a terminal table.",
        )
        get_parser.set_defaults(func=self._run_get)
        _add_gateway_arguments(get_parser, config.timeout)

        metrics_parser = commands.add_parser(
            "metrics",
            help="Serve current traffic at an HTTP /metrics endpoint",
            description=(
                "Start a long-running Prometheus metrics server. Each GET /metrics fetches "
                "fresh SSP traffic and optionally reports daily records to InfluxDB 3."
            ),
        )
        metrics_parser.set_defaults(func=self._run_metrics)
        _add_gateway_arguments(metrics_parser, config.timeout)
        metrics_parser.add_argument(
            "--host",
            type=_host,
            default="127.0.0.1",
            help="HTTP listen address (default: 127.0.0.1)",
        )
        metrics_parser.add_argument(
            "--port", type=_port, default=9101, help="HTTP listen port (default: 9101)"
        )
        metrics_parser.add_argument(
            "--push-influxdb",
            action="store_true",
            help="Enable InfluxDB 3 reporting after a database/token query check",
        )

    def _show_help(self, args: argparse.Namespace) -> int:
        if self._parser is not None:
            self._parser.print_help()
        return EXIT_SUCCESS

    def _run_get(self, args: argparse.Namespace) -> int:
        errors = SSPConsole(stderr=True)
        config = load_config().ssp
        source = _create_source(args, config, errors)
        if source is None:
            return EXIT_USAGE
        try:
            with source:
                SSPConsole().report(source.collect(), gateway=config.gateway_base_url)
        except TrafficCollectionError as exc:
            errors.error(str(exc))
            return EXIT_FAILURE
        return EXIT_SUCCESS

    def _run_metrics(self, args: argparse.Namespace) -> int:
        display = SSPConsole(stderr=True)
        display.configure_logging()
        config = load_config()
        source = _create_source(args, config.ssp, display)
        if source is None:
            return EXIT_USAGE
        try:
            with source:
                _serve_metrics(args, config, source)
        except KeyboardInterrupt:
            _LOGGER.info("SSP metrics server stopped.")
        except OSError as exc:
            display.error(f"Unable to run the metrics HTTP server: {exc}")
            return EXIT_FAILURE
        return EXIT_SUCCESS


def _serve_metrics(args: argparse.Namespace, config: AppConfig, source: SSPSource) -> None:
    with ExitStack() as resources:
        reporter = InfluxDB3Reporter(config.influxdb3, enabled=args.push_influxdb)
        resources.callback(reporter.close)
        registry = CollectorRegistry()
        scrape_duration = Gauge(
            "proxy_traffic_scrape_duration_seconds",
            "Time spent fetching and normalizing SSP traffic in seconds.",
            registry=registry,
        )

        @scrape_duration.time()
        def collect() -> TrafficSnapshot:
            return source.collect()

        exporter = TrafficExporter(collect, registry=registry, on_collect=reporter.report)
        server = resources.enter_context(MetricsHTTPServer(args.host, args.port, exporter.render))
        # Bind before probing InfluxDB. On exit, drain HTTP handlers before closing clients.
        reporter.start()
        _LOGGER.info("Serving SSP metrics at %s (Ctrl+C to stop).", server.metrics_url)
        server.serve_forever()


def _create_source(
    args: argparse.Namespace, config: SSPConfig, display: SSPConsole
) -> SSPSource | None:
    authorization = config.authorization if args.authorization is None else args.authorization
    if not authorization.strip():
        display.missing_authorization()
        return None
    try:
        return SSPSource(
            config,
            authorization=authorization,
            timeout=args.timeout,
            trace=display.trace if args.verbose else None,
        )
    except (SSPGatewayError, ValueError) as exc:
        display.error(f"Unable to initialize SSP collection: {exc}")
        return None


def _add_gateway_arguments(parser: argparse.ArgumentParser, timeout: float) -> None:
    parser.add_argument(
        "--authorization",
        default=None,
        help="Complete Bearer authorization value (overrides config)",
    )
    parser.add_argument(
        "--timeout", type=_timeout, default=timeout, help="Request timeout in seconds"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show redacted HTTP request and response transcripts",
    )


def _host(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("host must not be empty")
    return value.strip()


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _timeout(value: str) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be a finite positive number")
    return timeout
