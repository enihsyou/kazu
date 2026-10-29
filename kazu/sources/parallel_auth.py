"""Read Parallel CLI OAuth credentials and keep refreshed tokens in memory."""

import json
import time
from pathlib import Path

import httpx

from kazu.lib.measurements import MONEY_REMAINING
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources.api_http import get_json


class ParallelAuth:
    def __init__(self, timeout: float) -> None:
        self.path = Path.home() / ".config/parallel-web-tools/auth.json"
        self.timeout = timeout
        self.mtime = None
        self.token = None

    def collect(self) -> UsageSnapshot:
        try:
            if self.token is None or self.token["access_token_expires_at"] <= time.time():
                mtime = self.path.stat().st_mtime_ns
                if mtime != self.mtime:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    self.client_id = data["client_id"]
                    self.token = data["orgs"][data["selected_org_id"]]["control_api"]
                    self.mtime = mtime
                if self.token["access_token_expires_at"] <= time.time():
                    response = httpx.post(
                        "https://platform.parallel.ai/getServiceKeys/token",
                        data={
                            "grant_type": "refresh_token",
                            "client_id": self.client_id,
                            "refresh_token": self.token["refresh_token"],
                        },
                        timeout=self.timeout,
                    )
                    if not response.is_success:
                        raise CollectionError(
                            f"Parallel token refresh failed (HTTP {response.status_code})"
                        )
                    token = response.json()
                    token["access_token_expires_at"] = time.time() + token["expires_in"]
                    self.token = token
            data = get_json(
                "https://api.parallel.ai/account/service/v1/balance",
                headers={"Authorization": f"Bearer {self.token['access_token']}"},
                timeout=self.timeout,
            )
            balance = float(data["credit_balance_cents"]) / 100
        except (OSError, KeyError, TypeError, ValueError, httpx.RequestError):
            raise CollectionError("Parallel CLI authentication or response failed") from None
        return UsageSnapshot((MONEY_REMAINING.create(balance, currency="USD", scope="account"),))
