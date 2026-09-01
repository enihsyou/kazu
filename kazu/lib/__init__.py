"""Reusable protocol clients and structured data models."""

from kazu.lib.sspgateway import (
    APIResult,
    GatewayHTTPError,
    GatewayNetworkError,
    GatewayProtocolError,
    GatewayTrace,
    SSPGateway,
    SSPGatewayError,
    TrafficLogResult,
    TrafficRecord,
)

__all__ = [
    "APIResult",
    "GatewayHTTPError",
    "GatewayNetworkError",
    "GatewayProtocolError",
    "GatewayTrace",
    "SSPGateway",
    "SSPGatewayError",
    "TrafficLogResult",
    "TrafficRecord",
]
