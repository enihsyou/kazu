"""MiniMax China Token Plan quotas, following the official mmx quota response."""

from __future__ import annotations

import math
from typing import Any

from kazu.config import SourceConfig
from kazu.lib.measurements import (
    LLM_QUOTA_REMAINING_RATIO,
    LLM_QUOTA_RESET,
)
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources.api_http import get_json


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    if not math.isfinite(value) or value < 0:
        raise ValueError
    return float(value)


def _parse_quota(data: dict[str, Any]) -> UsageSnapshot:
    try:
        if "base_resp" in data and data["base_resp"]["status_code"] != 0:
            raise CollectionError("MiniMax quota query failed; check China Token Plan credentials")
        models = data["model_remains"]
        if not isinstance(models, list):
            raise ValueError
        measurements = []
        for model in models:
            name = model["model_name"]
            if not isinstance(name, str) or not name:
                raise ValueError
            for window, prefix, start_key, end_key in (
                ("interval", "current_interval", "start_time", "end_time"),
                ("week", "current_weekly", "weekly_start_time", "weekly_end_time"),
            ):
                # Zero totals and status=3 do not describe a finite allowance.
                if model.get(f"{prefix}_status") == 3:
                    continue
                total = model.get(f"{prefix}_total_count")
                percent = model.get(f"{prefix}_remaining_percent")
                if total is not None:
                    total = _number(total)
                if percent is not None:
                    ratio = _number(percent) / 100
                elif total:
                    # Legacy usage_count means remaining; newer APIs supply explicit percent.
                    ratio = _number(model[f"{prefix}_usage_count"]) / total
                else:
                    continue
                if ratio > 1:
                    raise ValueError
                if window == "week" and model.get("weekly_boost_permille") is not None:
                    ratio *= _number(model["weekly_boost_permille"]) / 1000
                end = _number(model[end_key]) / 1000
                start = _number(model[start_key]) / 1000
                duration = end - start
                if duration <= 0:
                    raise ValueError
                interval = f"{duration:g}s"
                for unit, seconds in (("w", 604800), ("d", 86400), ("h", 3600)):
                    if duration % seconds == 0:
                        interval = f"{duration / seconds:g}{unit}"
                        break
                labels = {"model": name, "interval": interval}
                measurements.append(LLM_QUOTA_REMAINING_RATIO.create(ratio, **labels))
                measurements.append(LLM_QUOTA_RESET.create(end, **labels))
    except (KeyError, TypeError, ValueError, OverflowError):
        raise CollectionError("MiniMax quota response has an invalid schema") from None
    return UsageSnapshot(
        tuple(measurements),
        warnings=() if measurements else ("No finite MiniMax quota data available",),
    )


class MiniMaxSource:
    mode = "api"

    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    def collect(self) -> UsageSnapshot:
        if self.config.source not in {"auto", "api"}:
            raise CollectionError("MiniMax quota supports auto or api sources")
        if not self.config.api_key.strip():
            raise CollectionError("MINIMAX_API_KEY is required (China Token Plan key)")
        if self.config.api_key.startswith("sk-api-"):
            raise CollectionError(
                "MiniMax quota requires a Token Plan key, not a pay-as-you-go key"
            )
        return _parse_quota(
            get_json(
                "https://api.minimax.cn/v1/token_plan/remains",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=self.config.timeout,
            )
        )

    def close(self) -> None:
        """One-shot requests hold no persistent resources."""
