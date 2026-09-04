from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kazu.lib.sspgateway.models import APIResult


class SSPGatewayError(RuntimeError):
    """Base error for gateway configuration, transport, and protocol failures."""


class GatewayNetworkError(SSPGatewayError):
    """The configured gateway request failed at the transport layer."""


class GatewayProtocolError(SSPGatewayError):
    """The gateway response could not be authenticated or decoded."""


class GatewayHTTPError(SSPGatewayError):
    """Report an HTTP failure returned by the SSP API."""

    def __init__(self, status_code: int, message: str, result: APIResult | None = None) -> None:
        super().__init__(f"SSP API returned HTTP {status_code}: {message}")
        self.status_code = status_code
        """Store the HTTP status code returned by the API."""

        self.result = result
        """Store the associated API result when one is available."""
