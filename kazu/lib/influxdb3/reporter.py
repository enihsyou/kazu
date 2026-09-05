from __future__ import annotations

import logging
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import Self

from kazu.config import InfluxDB3Config
from kazu.lib.influxdb3.client import InfluxDB3Client, InfluxDB3Error
from kazu.lib.influxdb3.traffic import InfluxDB3SubscriptionTrafficWriter
from kazu.lib.traffic import SubscriptionTrafficSnapshot

_LOGGER = logging.getLogger(__name__)
_QUEUE_SIZE = 1
_WORKER_POLL_SECONDS = 0.1


class InfluxDB3Reporter:
    """Opt-in reporting whose failures cannot stop metrics collection."""

    def __init__(self, config: InfluxDB3Config, *, enabled: bool) -> None:
        self._config = config
        self._requested = enabled
        self._started = False
        self._client: InfluxDB3Client | None = None
        self._writer: InfluxDB3SubscriptionTrafficWriter | None = None
        self._queue: Queue[SubscriptionTrafficSnapshot] | None = None
        self._worker: Thread | None = None
        self._stop_worker = Event()
        self._lifecycle_lock = Lock()
        self._accepting = False

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
            self._writer = InfluxDB3SubscriptionTrafficWriter(self._client)
            table_exists = self._writer.table_exists()
        except (InfluxDB3Error, OSError, ValueError) as exc:
            self.close()
            _LOGGER.warning(
                "InfluxDB reporting will not be enabled: %s. The metrics server will continue.",
                exc,
            )
            return
        self._queue = Queue(maxsize=_QUEUE_SIZE)
        self._stop_worker.clear()
        self._worker = Thread(
            target=self._run_worker,
            name="kazu-influxdb3-reporter",
            daemon=True,
        )
        self._accepting = True
        try:
            self._worker.start()
        except RuntimeError as exc:
            self._accepting = False
            self._queue = None
            self._worker = None
            self._writer = None
            self._client.close()
            self._client = None
            _LOGGER.warning(
                "InfluxDB reporting will not be enabled: unable to start the background "
                "worker (%s). The metrics server will continue.",
                type(exc).__name__,
            )
            return
        _LOGGER.info(
            "InfluxDB table check passed (table %s); traffic will be reported in the "
            "background. Write permission will be checked by actual writes.",
            "exists" if table_exists else "will be created on first write",
        )

    def report(self, snapshot: SubscriptionTrafficSnapshot) -> None:
        """Report a traffic snapshot without interrupting its caller."""
        with self._lifecycle_lock:
            queue = self._queue if self._accepting else None
            if queue is None:
                return
            try:
                queue.put_nowait(snapshot)
                return
            except Full:
                pass

            replaced = False
            try:
                queue.get_nowait()
            except Empty:
                pass
            else:
                queue.task_done()
                replaced = True
            try:
                queue.put_nowait(snapshot)
            except Full:
                _LOGGER.warning("InfluxDB reporting queue is full; dropping the latest snapshot.")
            else:
                if not replaced:
                    return
                _LOGGER.warning(
                    "InfluxDB reporting queue is full; replaced an older pending snapshot."
                )

    def close(self) -> None:
        """Close the optional InfluxDB reporting resources."""
        with self._lifecycle_lock:
            self._accepting = False
            worker = self._worker
            self._stop_worker.set()
        if worker is not None:
            worker.join(timeout=self._config.timeout * (_QUEUE_SIZE + 1) + 1)
            if worker.is_alive():
                _LOGGER.warning(
                    "InfluxDB background worker did not stop before the shutdown deadline."
                )
        with self._lifecycle_lock:
            self._queue = None
            self._worker = None
            self._writer = None
            if self._client is not None and worker is None:
                self._client.close()
            self._client = None

    def _run_worker(self) -> None:
        queue = self._queue
        writer = self._writer
        client = self._client
        if queue is None or writer is None or client is None:
            return
        try:
            while True:
                try:
                    item = queue.get(timeout=_WORKER_POLL_SECONDS)
                except Empty:
                    if self._stop_worker.is_set():
                        return
                    continue
                try:
                    try:
                        count = writer.write(item)
                    except (InfluxDB3Error, OSError, ValueError) as exc:
                        _LOGGER.error("Unable to report traffic to InfluxDB: %s", exc)
                    except Exception as exc:
                        _LOGGER.error(
                            "Unexpected InfluxDB reporting failure (%s).", type(exc).__name__
                        )
                    else:
                        _LOGGER.debug("Reported %d traffic records to InfluxDB.", count)
                finally:
                    queue.task_done()
        finally:
            client.close()
