FROM python:3.12-slim AS builder
WORKDIR /w
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV UV_SYSTEM_PYTHON=1
RUN uv pip wheel . -w /wheels

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels devops-ai
COPY src ./src
EXPOSE 8000
ENV PORT=8000
CMD ["python","-m","app.api.__main__"]
