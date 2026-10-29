"""Select official CLI or API usage without launching interactive login."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from kazu.config import SourceConfig
from kazu.lib.measurements import (
    CALLS_USED,
    CREDITS_CAP,
    CREDITS_REMAINING,
    MONEY_REMAINING,
)
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources import firecrawl_api, parallel_auth, tavily_api, tinyfish_api


def _run_json(command: str, args: list[str], timeout: float) -> dict[str, Any]:
    executable = shutil.which(command)
    if executable is None:
        raise CollectionError(f"CLI executable not found: {command}")
    try:
        result = subprocess.run(
            [executable, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CollectionError("CLI query timed out") from exc
    except OSError as exc:
        raise CollectionError(f"Unable to start CLI ({type(exc).__name__})") from exc
    # CLI output can contain credentials or request headers; never log it on failure.
    if result.returncode:
        raise CollectionError(f"CLI query exited with status {result.returncode}; check CLI login")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise CollectionError("CLI did not return valid JSON") from exc


def _tinyfish(command: str, timeout: float) -> UsageSnapshot:
    measurements = []
    warnings = []
    # Legacy credit accounts have no wallet, but can still expose search usage.
    for query in ("wallet", "search"):
        try:
            if query == "wallet":
                data = _run_json(command, ["wallet", "status"], timeout)
                measurements.append(
                    MONEY_REMAINING.create(
                        float(data["available_balance"]), currency=data["currency"], scope="account"
                    )
                )
            else:
                data = _run_json(command, ["search", "usage", "--limit", "1"], timeout)
                measurements.append(CALLS_USED.create(float(data["total"]), scope="all_time"))
        except (CollectionError, KeyError, TypeError, ValueError) as exc:
            detail = str(exc) if isinstance(exc, CollectionError) else "Unexpected JSON schema"
            warnings.append(f"{query}: {detail}")
    if not measurements:
        raise CollectionError("; ".join(warnings))
    return UsageSnapshot(tuple(measurements), warnings=tuple(warnings))


def _firecrawl(command: str, timeout: float) -> UsageSnapshot:
    result = _run_json(command, ["credit-usage", "--json"], timeout)
    if not result["success"]:
        raise CollectionError("Firecrawl credit query failed")
    data = result["data"]
    measurements = [CREDITS_REMAINING.create(float(data["remainingCredits"]), scope="account")]
    if data["planCredits"] > 0:
        measurements.append(CREDITS_CAP.create(float(data["planCredits"]), scope="plan"))
    # Remaining credits may include top-ups; their difference is not a reliable usage value.
    return UsageSnapshot(tuple(measurements))


def _parallel(command: str, timeout: float) -> UsageSnapshot:
    data = _run_json(command, ["balance", "--json", "get"], timeout)
    return UsageSnapshot(
        (
            MONEY_REMAINING.create(
                float(data["credit_balance_cents"]) / 100, currency="USD", scope="account"
            ),
        )
    )


CLI_COLLECTORS = {
    "tinyfish": ("tinyfish", _tinyfish),
    "firecrawl": ("firecrawl", _firecrawl),
    "parallel": ("parallel-cli", _parallel),
}
API_COLLECTORS: dict[str, Callable[[SourceConfig], UsageSnapshot]] = {
    "tinyfish": tinyfish_api.collect,
    "tavily": tavily_api.collect,
    "firecrawl": firecrawl_api.collect,
}


class SearchSource:
    def __init__(self, provider: str, config: SourceConfig) -> None:
        self.provider = provider
        self.config = config
        self.mode = config.source
        if self.mode == "auto":
            if provider in API_COLLECTORS and config.api_key.strip():
                self.mode = "api"
            elif provider in CLI_COLLECTORS and shutil.which(
                config.command or CLI_COLLECTORS[provider][0]
            ):
                self.mode = "cli"
            elif provider == "parallel":
                self.mode = "cli-auth"
            else:
                self.mode = "api"
        self.auth = (
            parallel_auth.ParallelAuth(config.timeout)
            if self.mode == "cli-auth" and provider == "parallel"
            else None
        )

    def collect(self) -> UsageSnapshot:
        config = self.config
        if self.mode == "cli-auth":
            if self.auth is None:
                raise CollectionError(f"{self.provider}: cli-auth is not supported")
            return self.auth.collect()
        if self.mode == "cli" and self.provider in CLI_COLLECTORS:
            command, collect = CLI_COLLECTORS[self.provider]
            try:
                snapshot = collect(config.command or command, config.timeout)
            except (CollectionError, KeyError, TypeError, ValueError) as exc:
                detail = (
                    str(exc) if isinstance(exc, CollectionError) else "Unexpected CLI JSON schema"
                )
                raise CollectionError(detail) from None
            return snapshot
        if self.mode == "cli":
            raise CollectionError(f"{self.provider} has no supported CLI usage command")
        if self.provider in API_COLLECTORS:
            return API_COLLECTORS[self.provider](config)
        raise CollectionError(f"{self.provider}: API usage collection is not supported")

    def close(self) -> None:
        """CLI commands and one-shot HTTP requests hold no persistent resources."""
