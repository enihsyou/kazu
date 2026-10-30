"""MiniMax quota semantics from official CLI fixtures, without live credentials."""

import pytest

from kazu.config import SourceConfig, load_config
from kazu.lib.measurements import (
    LLM_QUOTA_REMAINING_RATIO,
    LLM_QUOTA_RESET,
)
from kazu.lib.metrics.exporter import MetricsExporter
from kazu.lib.metrics.watch import WatchView
from kazu.lib.usage import CollectionError
from kazu.sources import minimax_api
from kazu.sources.registry import create_source


def test_legacy_counts_windows_and_metrics():
    # MiniMax-AI/cli test/fixtures/quota-response.json (38aba5f).
    snapshot = minimax_api._parse_quota(
        {
            "model_remains": [
                {
                    "model_name": "MiniMax-M*",
                    "start_time": 1776355200000,
                    "end_time": 1776373200000,
                    "current_interval_total_count": 1500,
                    "current_interval_usage_count": 228,
                    "current_weekly_total_count": 0,
                    "current_weekly_usage_count": 0,
                }
            ]
        }
    )
    values = {m.name: m.value for m in snapshot.measurements}
    assert values == {
        LLM_QUOTA_REMAINING_RATIO.name: 0.152,
        LLM_QUOTA_RESET.name: 1776373200,
    }

    class Watch:
        def consume(self):
            return WatchView(snapshot, True, True, snapshot.observed_at, 0.1)

    output = MetricsExporter({"minimax": Watch()}).render().decode()
    assert (
        'kazu_llm_quota_remaining_ratio{interval="5h",model="MiniMax-M*",'
        'provider="minimax"} 0.152' in output
    )
    assert 'interval="1w"' not in output
    assert "kazu_llm_quota_window_seconds" not in output


@pytest.mark.parametrize("count", [0, 5])
def test_explicit_percent_is_authoritative(count):
    snapshot = minimax_api._parse_quota(
        {
            "model_remains": [
                {
                    "model_name": "video",
                    "start_time": 1776355200000,
                    "end_time": 1776373200000,
                    "weekly_start_time": 1776009600000,
                    "weekly_end_time": 1776614400000,
                    "current_interval_total_count": 5,
                    "current_interval_usage_count": count,
                    "current_interval_remaining_percent": 100,
                    "current_weekly_remaining_percent": 75,
                    "weekly_boost_permille": 2000,
                }
            ]
        }
    )
    assert [
        (dict(m.labels)["interval"], m.value)
        for m in snapshot.measurements
        if m.name == LLM_QUOTA_REMAINING_RATIO.name
    ] == [
        ("5h", 1),
        ("1w", 1.5),
    ]


@pytest.mark.parametrize(
    "seconds, label",
    [
        (14400, "4h"),
        (18000, "5h"),
        (86400, "1d"),
        (604800, "1w"),
        (18001, "18001s"),
    ],
)
def test_interval_labels(seconds, label):
    snapshot = minimax_api._parse_quota(
        {
            "model_remains": [
                {
                    "model_name": "model",
                    "current_interval_remaining_percent": 50,
                    "start_time": 1776355200000,
                    "end_time": 1776355200000 + seconds * 1000,
                }
            ]
        }
    )
    assert all(
        dict(m.labels) == {"model": "model", "interval": label} for m in snapshot.measurements
    )


@pytest.mark.parametrize("percent", [-1, 101, True, "private-body", float("nan")])
def test_invalid_response_does_not_expose_values(percent):
    with pytest.raises(CollectionError, match="invalid schema") as error:
        minimax_api._parse_quota(
            {
                "model_remains": [
                    {
                        "model_name": "model",
                        "current_interval_remaining_percent": percent,
                    }
                ]
            }
        )
    assert "private-body" not in str(error.value)


def test_empty_and_unlimited_quotas_are_not_zero():
    for models in (
        [],
        [{"model_name": "model", "current_interval_status": 3, "current_interval_total_count": 0}],
    ):
        snapshot = minimax_api._parse_quota({"model_remains": models})
        assert not snapshot.measurements
        assert snapshot.warnings


def test_config_credentials_registry_and_request(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    path = tmp_path / "config.toml"
    path.write_text('[sources.minimax]\nenabled = true\nsource = "api"\n', encoding="utf-8")
    (tmp_path / ".env").write_text("MINIMAX_API_KEY=fixture-key\n", encoding="utf-8")

    def get_json(url, *, headers, timeout):
        assert url == "https://api.minimax.cn/v1/token_plan/remains"
        assert headers == {"Authorization": "Bearer fixture-key"}
        assert timeout == 30
        return {"base_resp": {"status_code": 0}, "model_remains": []}

    monkeypatch.setattr(minimax_api, "get_json", get_json)
    source = create_source("minimax", load_config(path))
    assert source.mode == "api"
    source.collect()
    monkeypatch.setenv("MINIMAX_API_KEY", "environment-key")
    assert load_config(path).providers["minimax"].api_key == "environment-key"


@pytest.mark.parametrize(
    "config",
    [
        SourceConfig(),
        SourceConfig(api_key="sk-api-example"),
        SourceConfig(source="cli", api_key="fixture-key"),
    ],
)
def test_unsupported_credentials_and_modes_do_not_request(monkeypatch, config):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid config must not call HTTP")

    monkeypatch.setattr(minimax_api, "get_json", unexpected)
    with pytest.raises(CollectionError):
        minimax_api.MiniMaxSource(config).collect()


def test_business_error_is_redacted():
    with pytest.raises(CollectionError, match="quota query failed") as error:
        minimax_api._parse_quota({"base_resp": {"status_code": 1004, "status_msg": "private-body"}})
    assert "private-body" not in str(error.value)
