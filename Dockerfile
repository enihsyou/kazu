# syntax=docker/dockerfile:1

FROM python:3.14-slim AS builder

# Keep the runtime image free of the uv binary itself. The latest uv release
# is used for every build.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Install locked third-party dependencies in a cacheable layer. Bind mounts
# keep the lock and metadata out of the intermediate image layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml,ro \
    --mount=type=bind,source=uv.lock,target=uv.lock,ro \
    uv sync \
        --locked \
        --no-dev \
        --no-install-project \
        --no-editable

COPY README.md ./
COPY kazu ./kazu
COPY docs ./docs

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml,ro \
    --mount=type=bind,source=uv.lock,target=uv.lock,ro \
    uv sync \
        --locked \
        --no-dev \
        --no-editable

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --link --from=builder /app/.venv /app/.venv

# platformdirs resolves the Linux user configuration to this directory.
VOLUME ["/root/.config/kazu"]
EXPOSE 9101

ENTRYPOINT ["kazu"]
