from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _read_payload() -> Mapping[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def _ruff_command(repository: Path) -> list[str]:
    return ["uv", "run", "ruff"]


def _run_ruff(repository: Path) -> tuple[bool, str]:
    command = _ruff_command(repository)
    steps = (("format", "."), ("check", "--fix", "."), ("check", "."))
    for arguments in steps:
        result = subprocess.run(
            [*command, *arguments],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip().splitlines()
            summary = detail[-1] if detail else f"exit code {result.returncode}"
            return False, f"Ruff {' '.join(arguments)} failed: {summary}"
    return True, ""


def _emit(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    payload = _read_payload()
    if payload.get("stop_hook_active") is True:
        _emit({})
        return 0

    try:
        repository = _repository_root()
        succeeded, reason = _run_ruff(repository)
    except (OSError, subprocess.SubprocessError) as exc:
        succeeded, reason = False, f"Unable to run Ruff: {exc}"

    _emit({} if succeeded else {"decision": "block", "reason": reason})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
