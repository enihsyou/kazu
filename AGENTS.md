# Repository guidance

- Prefer python executable in `.venv`, fallback to `uv run` when package is not installed.
- Do not run ruff manually, there is a hook which runs `ruff fmt` and `ruff check` on conversation stops.
- When invoking Ruff manually, prefer one batch: `ruff format . && ruff check --fix . && ruff check .`.
