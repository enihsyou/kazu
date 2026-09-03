from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from prometheus_client import CONTENT_TYPE_LATEST

from kazu.lib.metrics.exporter import MetricsUnavailable

_LOGGER = logging.getLogger(__name__)


class MetricsHTTPServer(ThreadingHTTPServer):
    """Serve only GET /metrics; drain active handlers before closing collectors."""

    daemon_threads = False
    """Keep handler threads alive until their requests finish."""

    block_on_close = True
    """Wait for active handler threads during server shutdown."""

    def __init__(self, host: str, port: int, render: Callable[[], bytes]) -> None:
        self.render = render
        """Store the callback used to render the metrics response."""

        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        self.address_family = addresses[0][0]
        """Store the address family selected for the listening socket."""

        super().__init__((host, port), MetricsRequestHandler)

    @property
    def metrics_url(self) -> str:
        """Return the URL served by the metrics endpoint."""
        host, port = self.server_address[:2]
        authority = f"[{host}]" if ":" in host else host
        return f"http://{authority}:{port}/metrics"

    def handle_error(self, request: object, client_address: object) -> None:
        """Log a generic handler failure without exposing request details."""
        # Avoid dumping request content or credentials from exception tracebacks.
        _LOGGER.error("Unexpected metrics HTTP handler failure.")


class MetricsRequestHandler(BaseHTTPRequestHandler):
    """Handle metrics endpoint requests for the metrics HTTP server."""

    server: MetricsHTTPServer
    """Reference the metrics server that owns this request handler."""

    timeout = 30
    """Set the request socket timeout in seconds."""

    def do_GET(self) -> None:
        """Serve the metrics endpoint for an HTTP GET request."""
        try:
            path = urlsplit(self.path).path
        except ValueError:
            self._respond(HTTPStatus.BAD_REQUEST, b"Invalid request path.\n")
            return
        if path != "/metrics":
            self._respond(HTTPStatus.NOT_FOUND, b"Not found. Metrics are at /metrics.\n")
            return
        try:
            body = self.server.render()
        except MetricsUnavailable as exc:
            self._respond(HTTPStatus.SERVICE_UNAVAILABLE, f"{exc}\n".encode())
            return
        except Exception as exc:
            _LOGGER.error("Unexpected metrics collection failure (%s).", type(exc).__name__)
            self._respond(HTTPStatus.INTERNAL_SERVER_ERROR, b"Metrics collection failed.\n")
            return
        self._respond(HTTPStatus.OK, body, CONTENT_TYPE_LATEST)

    def _respond(
        self, status: HTTPStatus, body: bytes, content_type: str = "text/plain; charset=utf-8"
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, TimeoutError):
            # A scraper can time out while upstream collection is still finishing.
            _LOGGER.debug("Metrics HTTP client disconnected before receiving the response.")

    def log_message(self, format: str, *args: object) -> None:
        """Suppress access logs that could expose arbitrary request URLs."""
        # Access logging can expose arbitrary URLs; collection failures are logged above.
        return
