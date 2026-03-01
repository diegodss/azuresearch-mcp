# azuresearch-mcp

Production-ready Python MCP server for per-application knowledge-base search with pluggable search providers and asynchronous ingestion pipelines.

## Architecture

```text
                           +--------------------------+
                           | Claude Desktop / MCP     |
                           +------------+-------------+
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
                              +---------+----------+       +---------------------+
                              | core/tool_factory  |       | providers/azure     |
                              | search_kb_<app_id> |       | providers/opensearch|
                              +--------------------+       +---------------------+

+---------------------- Async Ingestion Plane -----------------------+
| POST /ingestion/jobs -> JobStore(sqlite) -> Queue(local/servicebus)|
|                                         -> worker.py -> ingesters   |
| GET /ingestion/jobs/{id} <- status/progress in JobStore            |
+--------------------------------------------------------------------+
```

## Project layout

- `server.py`: FastAPI app exposing MCP and ingestion job APIs
- `worker.py`: queue consumer running ingestion asynchronously
- `core/auth.py`: bearer token + Entra JWT auth
- `core/tool_factory.py`: dynamic MCP tool generation from `config/apps.yaml`
- `core/search_provider.py`: provider abstraction
- `core/provider_factory.py`: runtime provider selector (`SEARCH_PROVIDER`)
- `core/job_store.py`: durable ingestion job tracking + local queue schema
- `core/queue_backend.py`: queue adapter (`local` sqlite or Azure Service Bus)
- `providers/azure_search.py`: Azure AI Search provider
- `providers/opensearch.py`: future provider stub
- `ingestion/*.py`: sharepoint/pdf/word/video ingestion pipelines
- `ingestion/runner.py`: shared ingestion orchestration used by worker

## Quickstart (Docker Compose)

1. Clone and configure env:

```bash
git clone https://github.com/diegodss/azuresearch-mcp.git
cd azuresearch-mcp
cp .env.example .env
```

2. Set required values in `.env` (minimum):

```bash
SEARCH_PROVIDER=azure
AZURE_SEARCH_ENDPOINT=https://<yourservice>.search.windows.net
AZURE_SEARCH_KEY=<your-key>
AUTH_MODE=token
MCP_API_KEY=<strong-token>
QUEUE_BACKEND=local
JOB_DB_PATH=data/jobs.db
```

3. Run API + worker:

```bash
mkdir -p data docs videos
docker compose up --build
```

4. Health check:

```bash
curl http://localhost:8000/healthz
```

## App registry (no code change)

Edit [`config/apps.yaml`](./config/apps.yaml) and restart.

```yaml
apps:
  - id: servicenow
    name: ServiceNow
    description: ITSM knowledge base
    index: kb-servicenow
```

New MCP tool is auto-generated as `search_kb_servicenow`.

## MCP API

Authenticated endpoint: `POST /mcp`

Methods:
- `initialize`
- `tools/list`
- `tools/call`

Example `tools/call` params:

```json
{
  "name": "search_kb_technologyone",
  "arguments": {"query": "reset password", "top": 5}
}
```

## Async ingestion API

### Create job

`POST /ingestion/jobs`

```json
{
  "app_id": "blackboard",
  "ingester_type": "pdf",
  "source": "/app/docs",
  "options": {"chunk_size": 1200},
  "idempotency_key": "pdf-batch-20260301"
}
```

### Check one job

`GET /ingestion/jobs/{job_id}`

### List jobs

`GET /ingestion/jobs?status=queued&limit=50`

### Cancel job

`POST /ingestion/jobs/{job_id}/cancel`

## Queue backends

### Local (default for dev)

```bash
QUEUE_BACKEND=local
JOB_DB_PATH=data/jobs.db
```

Jobs and queue metadata are stored in sqlite.

### Azure Service Bus (production)

```bash
QUEUE_BACKEND=servicebus
AZURE_SERVICEBUS_CONNECTION_STRING=Endpoint=sb://...
AZURE_SERVICEBUS_QUEUE_NAME=ingestion-jobs
JOB_DB_PATH=data/jobs.db
```

Service Bus handles delivery; sqlite still stores job lifecycle/status.

## Ingestion pipelines

All ingestion runs asynchronously via worker when submitted to `/ingestion/jobs`, but CLI commands are also available for one-off/manual operations.

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

Video ingestion uses Azure Video Indexer when `AZURE_VIDEO_INDEXER_KEY` is set; otherwise local Whisper (`openai-whisper` package required).

## Auth modes

`AUTH_MODE=token`
- Expects `Authorization: Bearer <MCP_API_KEY>`

`AUTH_MODE=entra`
- Validates Entra JWT signature against tenant JWKS
- Validates `aud` against `AZURE_CLIENT_ID`
- Validates issuer against `AZURE_TENANT_ID`

## Configure Claude Desktop

### Local MCP server

- URL: `http://localhost:8000/mcp`
- Header: `Authorization: Bearer <MCP_API_KEY>`

### Production MCP server

- URL: `https://<your-app>.azurewebsites.net/mcp`
- Header: token or Entra bearer token depending on `AUTH_MODE`

## Swap search provider

Set:

```bash
SEARCH_PROVIDER=azure
```

To add a new provider (OpenSearch, Pinecone, etc.), implement `core/search_provider.py` and wire it in `core/provider_factory.py`.

## CI/CD to Azure App Service

Workflow: [`.github/workflows/deploy.yml`](./.github/workflows/deploy.yml)

Trigger: push to `main`

Pipeline:
1. Build Docker image
2. Push image to Azure Container Registry
3. Deploy image to Azure App Service

Required GitHub secrets:
- `AZURE_CREDENTIALS`
- `ACR_LOGIN_SERVER`
- `ACR_USERNAME`
- `ACR_PASSWORD`
- `WEBAPP_NAME`

## `.env` reference

See [`.env.example`](./.env.example) for all runtime settings:
- Provider/search
- Auth
- Queue/worker/job store
- SharePoint ingestion
- Video ingestion

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn server:app --reload
python worker.py
```
