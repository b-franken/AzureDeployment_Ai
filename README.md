# Azure Copilot (DevOps AI)

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![Framework](https://img.shields.io/badge/FastAPI-API-green)
![Frontend](https://img.shields.io/badge/Next.js-Web%20UI-black)
![License](https://img.shields.io/badge/License-MIT-yellow)

Natural language provisioning and policy management for Azure.  
Describe the desired state (for example: "create an AKS cluster in westeurope") and the tool produces a safe plan with sensible defaults. Apply when ready.

---

## Features

- NL to Action: parse user intent, extract parameters, and return typed results
- Safe by default: plan or dry-run support with clear, structured output
- Idempotent ensure flows: avoids recreating existing resources
- Azure actions via SDK: initial set includes AKS and Traffic Manager profiles
- Strong typing and ergonomics: consistent tags (owner, env) and secret redaction on errors

Goal: a professional MVP internal teams can use with safe defaults and clear plans.

---

## Table of contents

- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [API server](#api-server-fastapi)
- [Web UI](#web-ui-nextjs)
- [Available Azure actions](#available-azure-actions-initial-set)
- [Architecture](#architecture)
- [Quality and CI](#quality--ci)
- [Safety](#safety)
- [License](#license)
- [Disclaimer](#disclaimer)

---

## Quickstart

### Requirements

- Python 3.12 or newer
- Azure access via Azure CLI (az login) or Service Principal

### Install

```bash
python -m pip install -U pip
pip install -e .
```

### Minimal usage (dry-run first)

```python
import asyncio
from app.tools.azure.tool import AzureProvision

async def main():
    tool = AzureProvision()
    res = await tool.run(
        action="create an aks cluster aks-dev in westeurope dns prefix aksdev",
        dry_run=True,
        env="dev",
        owner="team-devops",
    )
    print(res["summary"])
    print(res["output"])

asyncio.run(main())
```

Switch to apply:

```python
res = await tool.run(
    action="create traffic manager profile tm-prod with performance routing",
    dry_run=False,
    env="prod",
    owner="platform",
)
```

---

## Configuration

Configure via environment variables. A local .env file works well in development.

### Azure authentication

Use one of the following:

**1) Azure CLI**

```bash
az login
az account set --subscription <SUBSCRIPTION_ID>
```

**2) Service Principal**

```dotenv
AZURE_TENANT_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
AZURE_SUBSCRIPTION_ID=
```

### LLM provider selection

Set LLM_PROVIDER to choose a backend: openai (default), gemini, or ollama.

**OpenAI**

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=...
# Optional when using gateways
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
```

**Google Gemini**

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-1.5-pro
```

**Ollama**

```dotenv
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

---

## API server (FastAPI)

Run the API locally:

```bash
uvicorn app.api.main:app --reload --port 8000
# Health check:  GET http://localhost:8000/healthz
# Chat endpoint: POST http://localhost:8000/api/chat
```

### Docker for API

```bash
# from repo root
docker build -t azure-copilot-api -f src/app/api/Dockerfile .
docker run --rm -p 8000:8000 --env-file .env azure-copilot-api
```

---

## Web UI (Next.js)

The web UI lives in apps/web. Point it at your API base URL.

```bash
# Development
cd apps/web
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

Set `REVIEWER_ENDPOINT` to the reviewer service URL. Tests can instead enable mock reviews with `REVIEWER_USE_MOCK=true`.

### Docker for Web

```bash
# from apps/web
docker build -t azure-copilot-web --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 .
docker run --rm -p 3000:3000 azure-copilot-web
```

---

## Available Azure actions (initial set)

- AKS: create or ensure clusters (node count, networking profile, workload identity, ACR pull role)
- Traffic Manager: create or ensure profiles (routing method, TTL, monitor, endpoints)

More actions will be added iteratively. Always start with dry_run=True in new environments.

---

## Architecture

```
src/
└─ app/
   ├─ api/                # FastAPI app (routes v1 and v2, CORS, health)
   ├─ ai/                 # NLU mapping (intent to provisioning spec)
   └─ tools/
      ├─ azure/           # Azure clients, validators, and actions
      │  └─ actions/      # aks.py, traffic_manager.py, ...
      ├─ provision/       # Orchestrator and backends (SDK, Bicep plan)
      └─ registry.py      # Tool registration and loader
apps/
└─ web/                   # Next.js UI (standalone build)
```

High-level flow:

```
User text -> NLU mapping -> Provision spec -> Orchestrator
                 |                 |
                 +---- Preview plan (dry-run) ----> Apply (SDK)
```

---

## Quality & CI

Local quality gates:

```bash
ruff check .
mypy src
pytest -q
```

Suggested GitHub Actions (Python 3.12):

```yaml
name: ci
on: [push, pull_request]
jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: |
          python -m pip install -U pip
          pip install -e .
          pip install -U ruff mypy pytest
      - run: ruff check .
      - run: mypy src
      - run: pytest -q
```

---

## Safety

- Prefer dry-run first and keep dry-run checks in CI for new actions
- Use least privilege and prefer Managed Identity or Key Vault for secrets
- Add guardrails such as region or SKU allowlists and require approval before apply in production

---

## License

MIT (see LICENSE).

---

## Disclaimer

This tool can change cloud infrastructure. Validate costs, policies, and compliance for your environment before applying changes.
