# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY pyproject.toml README.* LICENSE* ./
COPY src ./src
RUN python -m pip install --upgrade pip wheel setuptools
RUN python -m pip wheel . -w /dist

FROM python:3.12-slim AS runtime
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH" AUDIT_DB_PATH=/data/audit.db
RUN adduser --disabled-password --gecos "" app \
    && mkdir -p /app /data \
    && chown -R app:app /app /data \
    && python -m venv /opt/venv
WORKDIR /app
COPY --from=builder /dist /dist
RUN python -m pip install --no-cache-dir /dist/*.whl && rm -rf /dist
EXPOSE 8000
USER app
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
