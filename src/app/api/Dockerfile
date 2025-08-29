FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update -y && apt-get install -y --no-install-recommends curl ca-certificates gnupg apt-transport-https build-essential && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /etc/apt/keyrings && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ bookworm main" > /etc/apt/sources.list.d/azure-cli.list
RUN apt-get update -y && apt-get install -y --no-install-recommends azure-cli libicu-dev && rm -rf /var/lib/apt/lists/*

RUN az bicep install
ENV PATH=/root/.azure/bin:$PATH
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false

COPY pyproject.toml /app/
COPY src /app/src

RUN python -m pip install --upgrade pip && pip install uv
RUN uv pip install --system .

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --retries=40 CMD curl -sf http://localhost:8000/api/health || exit 1
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]
