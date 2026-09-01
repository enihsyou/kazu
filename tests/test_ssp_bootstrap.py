"""Online checks that SSP's public bootstrap inputs have not drifted."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
import pytest

from kazu.lib.sspgateway import BOOTSTRAP_MASTER_KEY, SECURE_SETTING

SSP_HOME_URL = "https://s1.thefew01.top/"
_SECURE_SETTING_RE = re.compile(
    r"""<meta\s+[^>]*\bname=["']secure-setting["'][^>]*\bcontent=["'](?P<value>[^"']+)""",
    re.IGNORECASE,
)
_SEC_JS_RE = re.compile(r"""<script\s+[^>]*\bsrc=["'](?P<url>[^"']*sec\.js[^"']*)""", re.IGNORECASE)
_MASTER_KEY_RE = re.compile(
    r""":\s*["']\b(?P<value>[a-z0-9]{32})\b["']\s*,""",
)


def _get_text_or_skip(client: httpx.Client, url: str) -> str:
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.RequestError as exc:
        pytest.skip(f"SSP public bootstrap resources are unreachable: {exc}")
    except httpx.HTTPStatusError as exc:
        pytest.fail(f"SSP public bootstrap resource returned {exc.response.status_code}: {url}")
    return response.text


def _extract_secure_setting(html: str) -> str:
    match = _SECURE_SETTING_RE.search(html)
    assert match is not None, "SSP homepage does not expose secure-setting"
    return match["value"]


def _extract_sec_js_url(html: str) -> str:
    match = _SEC_JS_RE.search(html)
    assert match is not None, "SSP homepage does not link sec.js"
    return urljoin(SSP_HOME_URL, match["url"])


def _extract_bootstrap_master_keys(script: str) -> tuple[str, ...]:
    return tuple(match["value"] for match in _MASTER_KEY_RE.finditer(script))


@pytest.mark.network
def test_public_ssp_bootstrap_matches_built_in_constants() -> None:
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        homepage = _get_text_or_skip(client, SSP_HOME_URL)
        secure_setting = _extract_secure_setting(homepage)
        script = _get_text_or_skip(client, _extract_sec_js_url(homepage))

    bootstrap_master_keys = _extract_bootstrap_master_keys(script)
    assert BOOTSTRAP_MASTER_KEY in bootstrap_master_keys
    assert secure_setting == SECURE_SETTING
