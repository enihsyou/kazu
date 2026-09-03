"""Byte-exact public bootstrap inputs and authenticated decoding."""

from __future__ import annotations

# ruff: noqa: E501 -- the fixed encrypted bootstrap setting must remain byte-exact.
import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from kazu.lib.sspgateway.errors import GatewayProtocolError

BOOTSTRAP_MASTER_KEY = "218f1c43e24751dfeaa1a78e3643d84b"
"""Provide the fixed key used to authenticate the bundled bootstrap setting."""

SECURE_SETTING = "SC0IMUV8a3XGjNONp76L5pH7uwVmI1Ss0KomKd16B1K1aS6aldz5woo0yDST37m6mMR9Evch24J7JMesQJNglKZpYNG9n+iI1XtI2C1qSWkLAqZs9GLJgm01wP0zwXWIqyY/rILf8I/CNBemYFVZb1xc4Ua+ccmYZy+R5T3RMdL4e2/B152qhIcjHrI1GwAoHBGgW7xx1YRmJeyqbY8j2uwjLoeRw6a8n0oC52ZXAmsJA6pevzOXl30y2rBxzWeEvWU7g4ie8Ymdf0DjLFpDZyJfoQK4LteYYyfA8nKGZYmvZjOdvZ/2kNVxH7EyAB49UxbwU+IygsE/IIW5LoU2hfkpbMTYhanX1S8fszQJTj9GXqlAvmSY3Sol1qx8kWiQuiI1ncOKvqn1RmGka0oMSBsEt1WpIpjdKiiC53HBO7vsMTLeov6+zJJzQ6lXag4mXBqiHZFTmN0qN9rySa0jzOwgNd6q4r7MkmxFqVZuDiZcFqIdklGYrCRj37B4jCPaoD42n82S+4HEc1rle2ZJZBoArFm1d8nTMmPbq2uTctqSZAbcmYGylNhzTutwXF8kCh+zHLN3zoF7e+/wQ8x5za0kKJbM2+6F33tJ4mVUWSQdHu5Ds2LUlmAg2vF5gGCQvmUoho+SsMLCeVjwZ2ZKZh8X4Qr5ZdaQbwCR8z2OYJO6LiisitXlv9IgGfFwVQ4wXCqcSoFg1cNHc9qPfJJloasZK7mk8dqEwWx79UloQn08Ce4IqVL4uWEJhes9ng=="
"""Provide the fixed encrypted bootstrap setting published by SSP."""


@lru_cache(maxsize=1)
def load_bootstrap() -> Mapping[str, Any]:
    """Return the authenticated bootstrap configuration."""
    try:
        payload = base64.b64decode(SECURE_SETTING, validate=True)
    except ValueError as exc:
        raise GatewayProtocolError("Built-in SSP bootstrap setting is invalid") from exc
    if len(payload) < 33:
        raise GatewayProtocolError("Built-in SSP bootstrap setting is truncated")
    key_hash = hashlib.sha256(BOOTSTRAP_MASTER_KEY.encode()).digest()
    provided_mac, body = payload[:32], payload[32:]
    expected_mac = hmac.new(key_hash, body, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_mac, expected_mac):
        raise GatewayProtocolError("Built-in SSP bootstrap setting failed authentication")
    plaintext = bytes(value ^ key_hash[index % len(key_hash)] for index, value in enumerate(body))
    try:
        config = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayProtocolError("Built-in SSP bootstrap setting is not valid JSON") from exc
    if not isinstance(config, Mapping):
        raise GatewayProtocolError("Built-in SSP bootstrap setting has an invalid shape")
    return config
