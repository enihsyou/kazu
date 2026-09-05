from datetime import UTC, datetime
from threading import Event

from kazu.config import InfluxDB3Config
from kazu.lib.influxdb3.reporter import InfluxDB3Reporter
from kazu.lib.traffic import SubscriptionTrafficSnapshot


def _config() -> InfluxDB3Config:
    return InfluxDB3Config(
        host="https://influxdb.example.com",
        database="kazu",
        token="token",
        timeout=0.1,
    )


def _snapshot(second: int) -> SubscriptionTrafficSnapshot:
    return SubscriptionTrafficSnapshot(
        observed_at=datetime(2026, 9, 6, 12, 0, second, tzinfo=UTC),
        usages=(),
    )


def test_report_coalesces_pending_snapshot_without_waiting_for_worker(monkeypatch) -> None:
    write_started = Event()
    release_write = Event()
    written: list[SubscriptionTrafficSnapshot] = []

    class FakeClient:
        def __init__(self, config: InfluxDB3Config) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeWriter:
        def __init__(self, client: FakeClient) -> None:
            pass

        def table_exists(self) -> bool:
            return True

        def write(self, snapshot: SubscriptionTrafficSnapshot) -> int:
            written.append(snapshot)
            if len(written) == 1:
                write_started.set()
                assert release_write.wait(1)
            return 0

    monkeypatch.setattr("kazu.lib.influxdb3.reporter.InfluxDB3Client", FakeClient)
    monkeypatch.setattr(
        "kazu.lib.influxdb3.reporter.InfluxDB3SubscriptionTrafficWriter", FakeWriter
    )
    reporter = InfluxDB3Reporter(_config(), enabled=True)
    reporter.start()

    first = _snapshot(1)
    replaced = _snapshot(2)
    latest = _snapshot(3)
    reporter.report(first)
    assert write_started.wait(1)
    reporter.report(replaced)
    reporter.report(latest)
    release_write.set()
    reporter.close()

    assert written == [first, latest]


def test_failed_startup_table_check_disables_reporting(monkeypatch) -> None:
    client_closed = Event()

    class FakeClient:
        def __init__(self, config: InfluxDB3Config) -> None:
            pass

        def close(self) -> None:
            client_closed.set()

    class FakeWriter:
        def __init__(self, client: FakeClient) -> None:
            pass

        def table_exists(self) -> bool:
            raise ValueError("query failed")

    monkeypatch.setattr("kazu.lib.influxdb3.reporter.InfluxDB3Client", FakeClient)
    monkeypatch.setattr(
        "kazu.lib.influxdb3.reporter.InfluxDB3SubscriptionTrafficWriter", FakeWriter
    )
    reporter = InfluxDB3Reporter(_config(), enabled=True)

    reporter.start()
    reporter.report(_snapshot(1))
    reporter.close()

    assert client_closed.is_set()
