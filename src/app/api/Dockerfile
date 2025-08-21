FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update -y && apt-get install -y --no-install-recommends curl build-essential && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
COPY src /app/src

RUN python -m pip install --upgrade pip && pip install uv
RUN uv pip install --system .

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --retries=40 CMD curl -sf http://localhost:8000/api/health || exit 1
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]
