# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# uv is the lockfile/dep tool; copy it from the official image. Pinned per decision 020.
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/

WORKDIR /app

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
