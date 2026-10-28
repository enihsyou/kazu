"""Source-independent snapshots shared by terminal and Prometheus consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Protocol


class CollectionError(RuntimeError):
    """A source could not return usage data; messages must not contain credentials."""


@dataclass(frozen=True)
class Measurement:
    name: str
    help: str
    value: float
    labels: tuple[tuple[str, str], ...] = ()
    metric_type: str = "gauge"


@dataclass(frozen=True)
class UsageSnapshot:
    measurements: tuple[Measurement, ...]
    observed_at: float = field(default_factory=time)
    warnings: tuple[str, ...] = ()


class UsageSource(Protocol):
    mode: str

    def collect(self) -> UsageSnapshot: ...

    def close(self) -> None: ...
