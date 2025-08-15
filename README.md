# Azure AI: Azure Copilot

Natural‑language provisioning and policy management for Azure. Describe the desired state (for example, "create a web app in westeurope") and the tool produces a safe plan with sensible defaults. Apply when ready.

---

## Contents

* [Features](#features)
* [Quickstart](#quickstart)
* [Configuration](#configuration)

  * [Core](#core)
  * [Azure authentication](#azure-authentication)
  * [LLM providers](#llm-providers)
  * [Discord bot integration (optional)](#discord-bot-integration-optional)
* [Examples](#examples)
* [Safety](#safety)
* [Development](#development)
* [Architecture](#architecture)
* [Roadmap](#roadmap)
* [License](#license)
* [Disclaimer](#disclaimer)

---

## Features

* Natural language to action with extracted parameters and typed results
* Plan and dry‑run by default with clear, structured outputs
* Idempotent ensure flows with safe lookup helpers
* Azure actions via SDK: App Service Plan, Web App, Storage Account, SQL Server and DB, Redis, VNet and Private DNS, Private Endpoint and Private Link
* Consistent typing, redaction of secrets in errors, and standard tags (owner, env)

> Goal: a professional MVP that internal teams can use with safe defaults and clear plans.

---

## Quickstart

### Requirements

* Python 3.11+
* Azure access using Azure CLI (`az login`) or a Service Principal


### Install

```bash
python -m pip install -U pip
pip install -e .
# optional for typing
pip install -U types-PyYAML
```

### Minimal run

Configure credentials in your environment, then run one of the examples below. Always start with `dry_run=true`.

---

## Configuration

The application is configured through environment variables. You can place these in a local `.env` file or export them into your shell. An example file is provided below.

### Core

* `USE_API` — set to `1` to route requests through an external API instead of calling cloud SDKs directly. Default is unset.
* `API_BASE_URL` — base URL for the external API when `USE_API=1`.
* `LOG_LEVEL` — `DEBUG`, `INFO`, `WARNING`, `ERROR`. Default is `INFO`.

### Azure authentication

Use one of:

**1) Azure CLI**

* Run `az login` and select a subscription with `az account set --subscription <id>`.

**2) Service Principal**

* `AZURE_TENANT_ID`
* `AZURE_CLIENT_ID`
* `AZURE_CLIENT_SECRET`
* `AZURE_SUBSCRIPTION_ID`

> Production tip: prefer Managed Identity and Key Vault for secret storage where possible.



### LLM providers

Set `LLM_PROVIDER` to select a provider, then configure the matching variables. If multiple are set, the app will use `LLM_PROVIDER` when present.

#### OpenAI

* `LLM_PROVIDER=openai`
* `OPENAI_KEY`
* `OPENAI_MODEL` — for example, `gpt-4o`, `gpt-4.1`, or another available model
* `OPENAI_ORG_ID` (optional)
* `OPENAI_API_BASE` (optional, for gateways)


#### Google Gemini

* `LLM_PROVIDER=gemini`
* `GOOGLE_API_KEY` (or `GEMINI_API_KEY` depending on your SDK)
* `GEMINI_MODEL` — for example, `gemini-1.5-pro`


*`LLM_PROVIDER=ollama`
*`OLLAMA_HOST=http://localhost:11434`
*`OLLAMA_MODEL=llama3.2`

### Discord bot integration (optional)

If you wire this tool into a Discord bot, set the following:

* `DISCORD_TOKEN`
* `DISCORD_CLIENT_ID`
* `DISCORD_CLIENT_SECRET`

> Scope the bot token to the minimal permissions your bot needs.

### `.env` example

```dotenv
# Core
USE_API=1
API_BASE_URL=https://api.example.com
LOG_LEVEL=INFO

# Azure authentication (Service Principal)
AZURE_TENANT_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
AZURE_SUBSCRIPTION_ID=

# LLM selection
LLM_PROVIDER=openai

# OpenAI
OPENAI_KEY=
OPENAI_MODEL=gpt-4o



# Google Gemini
GOOGLE_API_KEY=
GEMINI_MODEL=gemini-1.5-pro

```

---
### Sample prompts:

```create storage account mydata123 in westeurope resource group myapp-dev-rg
create web app mywebapp in westeurope resource group myapp-dev-rg
create sql server mysqlsrv with admin sqladmin
link private dns zone privatelink.blob.core.windows.net to vnet rg/vnet-name
create private endpoint pe1 in rg myapp-dev-rg vnet myapp-dev-vnet subnet default target <resource_id>
```
---

## Examples

### Dry‑run provisioning

```python
import asyncio
from app.tools.azure.tool import AzureProvision

async def main():
    tool = AzureProvision()
    res = await tool.run(
        action="create a web app myweb in westeurope using a basic plan",
        dry_run=True,
        env="dev",
        owner="team-devops",
    )
    print(res["summary"])
    print(res["output"])

asyncio.run(main())
```

### Execute changes

```python
res = await tool.run(
    action="create storage account mydata123 in westeurope resource group myapp-dev-rg",
    dry_run=False,
    env="dev",
    owner="team-devops",
)
```

---

## Safety

* Dry‑run first, and keep dry‑run in CI
* Secrets and tokens are redacted in errors where possible
* Use least privilege; prefer Managed Identity and Key Vault over plain environment variables
* Add guardrails such as region and SKU allowlists and an approve‑before‑apply workflow

> This tool makes changes in cloud environments. Validate policies, costs, and compliance before applying.

---

## Development

### Quality gates

```bash
mypy src
ruff check .
pytest -q
```

**Suggested pyproject.toml**

```toml
[tool.mypy]
python_version = "3.11"
warn_unused_ignores = true
warn_return_any = true
disallow_untyped_defs = true
no_implicit_optional = true
strict_optional = true

[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E","F","I","UP","B","C4","PIE","PT","RUF"]
ignore = ["E501"]
```

**Minimal GitHub Actions workflow**

```yaml
name: ci
on:
  push:
  pull_request:

jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: install
        run: |
          python -m pip install -U pip
          pip install -e .
          pip install -U types-PyYAML pytest ruff mypy
      - name: ruff
        run: ruff check .
      - name: mypy
        run: mypy src
      - name: tests
        run: pytest -q
```

---

## Architecture

* `app/tools/azure/*` — Azure clients, validators, and actions
* `app/tools/azure/tool.py` — natural‑language parser and action orchestration
* `app/tools/provision/*` — provisioning orchestrator and backends (SDK, Terraform, Bicep)
* `app/ai/*` — NLU intent parsing and tool registration

---

## Roadmap

* Retries with jitter and consistent error envelopes
* Stronger idempotency with human‑readable diffs
* Observability: structured logs, tracing, audit events
* CLI with plan and apply and example playbooks
* More actions such as Key Vault access policies, AKS node pools, app settings and secrets
* Integration tests with mocked SDKs
* Guardrails for destructive actions


---

## Disclaimer

Use at your own risk. Validate policies, costs, and compliance requirements in your own environment before applying changes.
