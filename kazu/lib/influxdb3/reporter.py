from __future__ import annotations

import logging
from typing import Self

from kazu.config import InfluxDB3Config
from kazu.lib.influxdb3.client import InfluxDB3Client, InfluxDB3Error
from kazu.lib.influxdb3.traffic import InfluxDB3DailyWriter
from kazu.lib.traffic import TrafficSnapshot

_LOGGER = logging.getLogger(__name__)


class InfluxDB3Reporter:
    """Opt-in reporting whose failures cannot stop metrics collection."""

    def __init__(self, config: InfluxDB3Config, *, enabled: bool) -> None:
        self._config = config
        self._requested = enabled
        self._started = False
        self._client: InfluxDB3Client | None = None
        self._writer: InfluxDB3DailyWriter | None = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        """Start optional InfluxDB reporting when configuration is usable."""
        if self._started:
            return
        self._started = True
        if not self._requested:
            _LOGGER.info("InfluxDB reporting is disabled; use --push-influxdb to enable it.")
            return
        try:
            self._client = InfluxDB3Client(self._config)
            self._client.check_connection()
        except (InfluxDB3Error, OSError, ValueError) as exc:
            self.close()
            _LOGGER.warning(
                "InfluxDB reporting will not be enabled: %s. The metrics server will continue.",
                exc,
            )
            return
        self._writer = InfluxDB3DailyWriter(self._client)
        _LOGGER.info(
            "InfluxDB database/token query check passed; traffic will be reported to InfluxDB. "
            "Write permission will be checked by actual writes."
        )

    def report(self, snapshot: TrafficSnapshot) -> None:
        """Report a traffic snapshot without interrupting its caller."""
        if self._writer is None:
            return
        try:
            count = self._writer.write(snapshot)
        except (InfluxDB3Error, OSError, ValueError) as exc:
            _LOGGER.error("Unable to report traffic to InfluxDB: %s", exc)
            return
        _LOGGER.debug("Reported %d traffic records to InfluxDB.", count)

    def close(self) -> None:
        """Close the optional InfluxDB reporting resources."""
        self._writer = None
        if self._client is not None:
            self._client.close()
            self._client = None
