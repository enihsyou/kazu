from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
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


def _normalize_paths(lines: list[str]) -> list[str]:
    if sys.platform != "win32":
        return lines

    normalized: list[str] = []
    for line in lines:
        path, separator, details = line.partition(":")
        if not separator:
            normalized.append(line)
            continue
        normalized.append(f"{PureWindowsPath(path).as_posix()}:{details}")
    return normalized


def _run_ruff(repository: Path) -> tuple[bool, str]:
    command = ["uv", "run", "ruff"]
    steps = (
        ("format", "."),
        ("check", "--quiet", "--respect-gitignore", "--output-format=concise"),
    )
    for arguments in steps:
        result = subprocess.run(
            [*command, *arguments],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            detail = "\n".join(_normalize_paths(detail.splitlines()))
            return False, f"Ruff `{arguments[0]}` failed:\n{detail}"
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
