"""Parallel device OAuth with persistent, rotating refresh tokens."""

import json
import logging
import os
import platform
import tempfile
import time
from pathlib import Path

import httpx

from kazu.lib.measurements import MONEY_REMAINING
from kazu.lib.usage import CollectionError, UsageSnapshot
from kazu.sources.api_http import get_json

_LOGGER = logging.getLogger(__name__)
_BASE_URL = "https://platform.parallel.ai/getServiceKeys"


class ParallelAuth:
    def __init__(self, timeout: float, path: Path) -> None:
        self.path = path
        self.timeout = timeout
        self.state = None

    def _post(self, endpoint: str, *, allowed_errors=(), deadline=None, **kwargs) -> dict:
        timeout = self.timeout
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0:
                raise CollectionError("Parallel OAuth authorization timed out (5 minutes)")
        response = httpx.post(
            f"{_BASE_URL}/{endpoint}",
            headers={"Accept": "application/json"},
            timeout=timeout,
            **kwargs,
        )
        data = response.json()
        if not isinstance(data, dict):
            raise CollectionError("Parallel OAuth did not return a JSON object")
        if data.get("error") in allowed_errors:
            return data
        if not response.is_success or "error" in data:
            raise CollectionError(f"Parallel OAuth {endpoint} failed (HTTP {response.status_code})")
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement avoids truncating the only refresh token during a restart.
        descriptor, name = tempfile.mkstemp(dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(self.state, output)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _store_token(self, token: dict) -> None:
        access_token = token["access_token"]
        refresh_token = token.get("refresh_token", self.state.get("refresh_token"))
        expires_in = float(token["expires_in"])
        if not isinstance(access_token, str) or not access_token or not refresh_token:
            raise CollectionError("Parallel OAuth returned invalid tokens")
        self.state.update(
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=time.time() + expires_in,
        )
        self._save()

    def _authorize(self) -> None:
        deadline = time.monotonic() + 300
        if not self.state.get("client_id"):
            client = self._post(
                "register",
                deadline=deadline,
                json={
                    "client_name": "kazu",
                    "platform": {
                        "machine": platform.machine(),
                        "os_name": os.name,
                        "processor": platform.processor(),
                        "release": platform.release(),
                        "system": platform.system(),
                        "version": platform.version(),
                    },
                },
            )
            self.state["client_id"] = client["client_id"]
            self._save()
        while time.monotonic() < deadline:
            device = self._post(
                "device/code",
                deadline=deadline,
                data={"client_id": self.state["client_id"], "scope": "balance:read"},
            )
            device_deadline = min(deadline, time.monotonic() + float(device["expires_in"]))
            interval = max(5, float(device.get("interval", 5)))
            _LOGGER.info(
                "Parallel OAuth: authorize at %s (code: %s); waiting up to 5 minutes.",
                device.get("verification_uri_complete") or device["verification_uri"],
                device["user_code"],
            )
            while time.monotonic() < device_deadline:
                time.sleep(min(interval, max(0, device_deadline - time.monotonic())))
                if time.monotonic() >= device_deadline:
                    break
                token = self._post(
                    "token",
                    deadline=device_deadline,
                    allowed_errors=(
                        "authorization_pending",
                        "slow_down",
                        "access_denied",
                        "expired_token",
                    ),
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "client_id": self.state["client_id"],
                        "device_code": device["device_code"],
                    },
                )
                error = token.get("error")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                elif error == "access_denied":
                    raise CollectionError("Parallel OAuth authorization denied")
                elif error == "expired_token":
                    break
                else:
                    self._store_token(token)
                    _LOGGER.info("Parallel OAuth authorization succeeded.")
                    return
        raise CollectionError("Parallel OAuth authorization timed out (5 minutes)")

    def collect(self) -> UsageSnapshot:
        try:
            if self.state is None:
                self.state = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {}
                if not isinstance(self.state, dict):
                    raise CollectionError("Parallel OAuth credentials must be a JSON object")
            if self.state.get("access_token_expires_at", 0) <= time.time():
                if self.state.get("refresh_token"):
                    token = self._post(
                        "token",
                        allowed_errors=("invalid_grant",),
                        data={
                            "grant_type": "refresh_token",
                            "refresh_token": self.state["refresh_token"],
                        },
                    )
                    if token.get("error") == "invalid_grant":
                        self._authorize()
                    else:
                        self._store_token(token)
                else:
                    self._authorize()
            data = get_json(
                "https://api.parallel.ai/account/service/v1/balance",
                headers={"Authorization": f"Bearer {self.state['access_token']}"},
                timeout=self.timeout,
            )
            balance = float(data["credit_balance_cents"]) / 100
        except (OSError, KeyError, TypeError, ValueError, httpx.RequestError) as exc:
            detail = "invalid JSON or numeric value" if isinstance(exc, ValueError) else str(exc)
            raise CollectionError(
                "Parallel OAuth authentication, storage, or response failed "
                f"({type(exc).__name__}): {detail}"
            ) from None
        return UsageSnapshot((MONEY_REMAINING.create(balance, currency="USD", scope="account"),))
