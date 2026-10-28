"""One independent background worker per source, suspended when nobody scrapes it."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Condition, Thread
from time import monotonic

from kazu.config import SourceConfig
from kazu.lib.usage import CollectionError, UsageSnapshot, UsageSource

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchView:
    snapshot: UsageSnapshot | None
    success: bool
    watching: bool
    last_success: float
    duration: float


class SourceWatch:
    def __init__(self, name: str, source: UsageSource, config: SourceConfig) -> None:
        self.name = name
        self.source = source
        self.config = config
        self._condition = Condition()
        self._snapshot: UsageSnapshot | None = None
        self._success = False
        self._last_success = 0.0
        self._duration = 0.0
        self._uncollected = 0
        self._paused = False
        self._stopped = False
        self._thread = Thread(target=self._run, name=f"watch-{name}", daemon=True)

    def start(self) -> None:
        self._thread.start()
        _LOGGER.info("%s Watch started (interval=%ss).", self.name, self.config.interval)

    def consume(self) -> WatchView:
        with self._condition:
            self._uncollected = 0
            # Capture the view before notifying: even an instant refresh cannot leak
            # into the scrape that woke this source. Pausing has already cleared its cache.
            view = WatchView(
                self._snapshot,
                self._success,
                not self._paused,
                self._last_success,
                self._duration,
            )
            if self._paused:
                self._paused = False
                self._condition.notify_all()
                _LOGGER.info("%s Watch resumed by Collect.", self.name)
            return view

    def close(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
        # In-flight commands have their own timeout; do not block shutdown on them.
        self._thread.join(timeout=1)

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    if self._stopped:
                        return
                    # Give Collect one full interval to consume the last result before
                    # pausing. This also makes idle_poll_limit=1 useful.
                    if self._uncollected >= self.config.idle_poll_limit:
                        self._paused = True
                        self._snapshot = None
                        self._success = False
                        _LOGGER.info(
                            "%s Watch paused after %d polls without Collect.",
                            self.name,
                            self._uncollected,
                        )
                    self._condition.wait_for(lambda: self._stopped or not self._paused)
                    if self._stopped:
                        return
                started = monotonic()
                snapshot = None
                try:
                    snapshot = self.source.collect()
                    for warning in snapshot.warnings:
                        _LOGGER.warning("%s: %s", self.name, warning)
                except Exception as exc:
                    # A provider must not terminate another worker or expose raw CLI output.
                    detail = str(exc) if isinstance(exc, CollectionError) else type(exc).__name__
                    _LOGGER.warning("%s query failed: %s", self.name, detail)
                with self._condition:
                    if self._stopped:
                        return
                    self._snapshot = snapshot
                    self._success = snapshot is not None and not snapshot.warnings
                    self._duration = monotonic() - started
                    if snapshot is not None:
                        self._last_success = snapshot.observed_at
                    self._uncollected += 1
                    self._condition.wait_for(lambda: self._stopped, timeout=self.config.interval)
        finally:
            self.source.close()
            _LOGGER.info("%s Watch stopped.", self.name)
