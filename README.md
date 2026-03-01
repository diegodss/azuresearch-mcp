# azuresearch-mcp

Production-ready Python MCP server for per-application knowledge-base search with pluggable search providers and ingestion pipelines.

## Architecture

```text
                        +------------------------------+
                        |      Claude Desktop / MCP    |
                        +---------------+--------------+
                                        |
                                        | JSON-RPC tools/list + tools/call
                                        v
+----------------------+      +---------+----------+      +----------------------+
| config/apps.yaml     | ---> | FastAPI MCP Server | ---> | SearchProvider (ABC) |
| app registry         |      | server.py          |      +----------+-----------+
+----------------------+      +---------+----------+                 |
                                        |                            |
                                        | dynamic tool factory       |
                                        v                            v
                              +---------+----------+       +---------+---------+
                              | core/tool_factory  |       | providers/azure   |
                              | search_kb_<app_id> |       | providers/opensearch|
                              +--------------------+       +-------------------+

+------------------- Ingestion Pipelines -------------------+
| sharepoint | pdf | word | video -> normalized chunks -> ingest() |
+---------------------------------------------------------------+
```

## Quickstart (Docker Compose)

1. Clone and configure env:

```bash
git clone https://github.com/diegodss/azuresearch-mcp.git
cd azuresearch-mcp
cp .env.example .env
```

2. Set required envs in `.env`:

```bash
SEARCH_PROVIDER=azure
AZURE_SEARCH_ENDPOINT=https://<yourservice>.search.windows.net
AZURE_SEARCH_KEY=<your-key>
AUTH_MODE=token
MCP_API_KEY=<strong-token>
```

3. Start server:

```bash
docker compose up --build
```

4. Health check:

```bash
curl http://localhost:8000/healthz
```

## App Registry: add a new app without code changes

Edit [`config/apps.yaml`](./config/apps.yaml):

```yaml
apps:
  - id: servicenow
    name: ServiceNow
    description: ITSM knowledge base
    index: kb-servicenow
```

Restart server. New tool `search_kb_servicenow` will be auto-registered.

## MCP methods

Authenticated endpoint: `POST /mcp`

- `initialize`
- `tools/list`
- `tools/call` with:

```json
{
  "name": "search_kb_technologyone",
  "arguments": {"query": "reset password", "top": 5}
}
```

## Ingestion commands

SharePoint:

```bash
python -m ingestion.sharepoint_ingester --app technologyone --site-url https://contoso.sharepoint.com/sites/ERP
```

PDF:

```bash
python -m ingestion.pdf_ingester --app blackboard --path ./docs/
```

Word:

```bash
python -m ingestion.word_ingester --app technologyone --path ./word-docs/
```

Video:

```bash
python -m ingestion.video_ingester --app dynamics365 --path ./videos/
```

Video ingester uses Azure Video Indexer when `AZURE_VIDEO_INDEXER_KEY` is set, otherwise local Whisper (`openai-whisper` package required).

## Auth modes

`AUTH_MODE=token`
- Expects `Authorization: Bearer <MCP_API_KEY>`

`AUTH_MODE=entra`
- Validates Azure AD JWT signature via tenant JWKS
- Validates `aud` against `AZURE_CLIENT_ID`
- Validates issuer against `AZURE_TENANT_ID`

## Configure Claude Desktop

### Local MCP server (HTTP)

1. Run this server on your machine (`docker compose up`).
2. Configure your Claude Desktop MCP connection to call your local URL:
   - URL: `http://localhost:8000/mcp`
   - Header: `Authorization: Bearer <MCP_API_KEY>`

### Production MCP server (Azure App Service)

1. Deploy this container to Azure App Service.
2. Configure environment variables in App Service.
3. Set Claude Desktop MCP endpoint to:
   - URL: `https://<your-app>.azurewebsites.net/mcp`
   - Header: token or Entra bearer token depending on `AUTH_MODE`.

## Swap search providers

Provider is selected with:

```bash
SEARCH_PROVIDER=azure
```

Future provider implementations only need to implement `core/search_provider.py` and then be wired in `core/provider_factory.py`.

## CI/CD to Azure App Service

Workflow: [`.github/workflows/deploy.yml`](./.github/workflows/deploy.yml)

Trigger: push to `main`.

Steps:
1. Build container image.
2. Push to Azure Container Registry.
3. Deploy image to Azure App Service.

Required GitHub repository secrets:
- `AZURE_CREDENTIALS`
- `ACR_LOGIN_SERVER`
- `ACR_USERNAME`
- `ACR_PASSWORD`
- `WEBAPP_NAME`

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn server:app --reload
```
