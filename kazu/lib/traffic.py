"""Provider-independent traffic values and collection contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


class TrafficCollectionError(RuntimeError):
    """A source could not produce a valid traffic snapshot."""


@dataclass(frozen=True)
class SubscriptionTrafficUsage:
    """Represent one provider's traffic usage for a business date."""

    provider: str
    """Identify the source provider of the usage."""

    user_id: str
    """Identify the subscription user associated with the usage."""

    usage_date: date
    """Store the business date covered by the usage."""

    server_rate: str
    """Store the provider's billing multiplier as text."""

    upload_bytes: int
    """Store the cumulative uploaded byte count."""

    download_bytes: int
    """Store the cumulative downloaded byte count."""

    deducted_bytes: int
    """Store the cumulative billed byte count."""


@dataclass(frozen=True)
class TrafficSnapshot:
    """Capture traffic usages observed at one collection instant."""

    observed_at: datetime
    """Record when the snapshot was collected."""

    usages: tuple[SubscriptionTrafficUsage, ...]
    """Contain the traffic usages included in the snapshot."""

    @property
    def today(self) -> date:
        """Return the local business date of the observation."""
        return self.observed_at.astimezone().date()

    @property
    def current_usages(self) -> tuple[SubscriptionTrafficUsage, ...]:
        """Return usages belonging to the observation's business date."""
        return tuple(usage for usage in self.usages if usage.usage_date == self.today)


class TrafficSource(Protocol):
    """Define the contract for collecting provider traffic snapshots."""

    def collect(self) -> TrafficSnapshot:
        """Fetch fresh usage data, or raise TrafficCollectionError."""
        ...
