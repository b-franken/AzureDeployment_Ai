# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Optional build arg to include extras like [nlp]
ARG PIP_EXTRAS=""

# System deps for building and terraform
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg unzip git && \
    rm -rf /var/lib/apt/lists/*

# Install Terraform CLI
ARG TF_VERSION=1.9.5
RUN curl -fsSL https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin \
    && rm -f /tmp/terraform.zip \
    && terraform -version

WORKDIR /app

# Copy only project metadata first for fast layer caching
COPY pyproject.toml README.md ./

# Install project in editable mode without extras by default
RUN python -m pip install -U pip \
    && pip install -e .${PIP_EXTRAS:+[}${PIP_EXTRAS}${PIP_EXTRAS:+]}

# Now copy the actual source
COPY src ./src

EXPOSE 8000
ENV PORT=8000

# Entrypoint for FastAPI
CMD ["python", "-m", "app.api.__main__"]
