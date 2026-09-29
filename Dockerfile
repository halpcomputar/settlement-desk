# syntax=docker/dockerfile:1
FROM python:3.14-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python

FROM python:3.14-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="Settlement desk" \
      org.opencontainers.image.description="Private settlement review dashboard" \
      org.opencontainers.image.source="https://github.com/halpcomputar/settlement-desk"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    SETTLEMENT_DB=/app/data/settlements.sqlite3 \
    SETTLEMENT_PORT=8765
WORKDIR /app
RUN groupadd --gid 10001 desk \
    && useradd --uid 10001 --gid desk --no-create-home --shell /usr/sbin/nologin desk \
    && mkdir /app/data \
    && chown desk:desk /app/data
COPY --from=builder /app/.venv /app/.venv
COPY server.py ./
COPY static/ ./static/
COPY sample/ ./sample/
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)" || exit 1
# Listen on the container interface; Compose publishes it only on host loopback.
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8765", "--no-access-log", "--no-proxy-headers"]
