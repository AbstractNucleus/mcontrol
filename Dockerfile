# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# uv is the lockfile/dep tool; copy it from the official image.
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/

WORKDIR /app

# Docker CLI + compose v2 plugin, used by mcontrol to recreate per-server
# containers when the .env (RCON_PASSWORD) changes.
ARG DOCKER_CE_CLI_VERSION=5:27.4.0-1~debian.12~bookworm
ARG DOCKER_COMPOSE_PLUGIN_VERSION=2.31.0-1~debian.12~bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        "docker-ce-cli=${DOCKER_CE_CLI_VERSION}" \
        "docker-compose-plugin=${DOCKER_COMPOSE_PLUGIN_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for cache friendliness.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/

# Install the project itself (editable metadata only; src is already there).
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Healthcheck uses urllib (already in the slim image) so we don't pull curl in just for this.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz').read()" || exit 1

CMD ["uv", "run", "--no-dev", "uvicorn", "mcontrol.main:app", "--host", "0.0.0.0", "--port", "8000"]
