from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def is_installed() -> bool:
    return shutil.which("agent-browser") is not None


def run_agent_browser(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agent-browser", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def parse_json_output(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ValueError("agent-browser returned empty output")

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"agent-browser returned non-JSON output: {text}") from exc

    # agent-browser eval can return a JSON string payload.
    if isinstance(data, str):
        try:
            nested = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"agent-browser returned JSON string but inner payload is invalid: {data}"
            ) from exc
        if not isinstance(nested, dict):
            raise ValueError("Parsed payload is not an object")
        return nested

    if not isinstance(data, dict):
        raise ValueError("Parsed payload is not an object")

    return data
