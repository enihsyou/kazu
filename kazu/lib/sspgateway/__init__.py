"""Read-only SSP gateway API; implementation details live in focused modules."""

from kazu.lib.sspgateway.bootstrap import BOOTSTRAP_MASTER_KEY, SECURE_SETTING
from kazu.lib.sspgateway.client import (
    DEFAULT_API_BASE_URL,
    DEFAULT_GATEWAY_BASE_URL,
    DEFAULT_TRAFFIC_ENDPOINT,
    SSPGateway,
)
from kazu.lib.sspgateway.errors import (
    GatewayHTTPError,
    GatewayNetworkError,
    GatewayProtocolError,
    SSPGatewayError,
)
from kazu.lib.sspgateway.models import (
    APIResult,
    GatewayResponse,
    GatewayTrace,
    TraceCallback,
    TrafficLogResult,
    TrafficRecord,
)

__all__ = [
    "BOOTSTRAP_MASTER_KEY",
    "SECURE_SETTING",
    "DEFAULT_API_BASE_URL",
    "DEFAULT_GATEWAY_BASE_URL",
    "DEFAULT_TRAFFIC_ENDPOINT",
    "SSPGateway",
    "SSPGatewayError",
    "GatewayHTTPError",
    "GatewayNetworkError",
    "GatewayProtocolError",
    "APIResult",
    "GatewayResponse",
    "GatewayTrace",
    "TraceCallback",
    "TrafficLogResult",
    "TrafficRecord",
]
