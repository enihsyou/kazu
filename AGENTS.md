# Repository guidance

- Python code uses Ruff. Formatting is not a concern while actively developing; run lint only at useful milestones.
- When invoking Ruff manually, prefer one batch: `ruff format . && ruff check --fix . && ruff check .`.
