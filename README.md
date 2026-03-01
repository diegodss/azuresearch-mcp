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

## Test without Azure credentials (recommended first run)

Use the built-in mock provider so `search_kb_technologyone` returns deterministic data locally.

1. In `.env` set:

```bash
SEARCH_PROVIDER=mock
MOCK_SEARCH_DATA_PATH=config/mock_search_data.json
AUTH_MODE=token
MCP_API_KEY=dev-token
QUEUE_BACKEND=local
JOB_DB_PATH=data/jobs.db
```

2. Start services:

```bash
docker compose up --build
```

3. List tools:

```bash
curl -s http://localhost:8000/mcp \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

4. Call `search_kb_technologyone`:

```bash
curl -s http://localhost:8000/mcp \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_kb_technologyone","arguments":{"query":"reset password","top":3}}}'
```

Expected: response includes text similar to `Reset your TechnologyOne password`.

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
No extra infrastructure is required beyond the container volume that persists `data/jobs.db`.

### Azure Service Bus (production)

```bash
QUEUE_BACKEND=servicebus
AZURE_SERVICEBUS_CONNECTION_STRING=Endpoint=sb://...
AZURE_SERVICEBUS_QUEUE_NAME=ingestion-jobs
JOB_DB_PATH=data/jobs.db
```

Service Bus handles delivery; sqlite still stores job lifecycle/status.

## Infrastructure requirements (what you actually need)

### Do I need an extra database?

- Current implementation: no separate DB server is required.
- Job status and metadata are stored in sqlite (`JOB_DB_PATH`, default `data/jobs.db`).
- Important for production: sqlite is best for single-node deployments. If you plan to run multiple API/worker replicas, use a shared SQL backend (for example Postgres/Azure SQL) by replacing `core/job_store.py`.

### Do I need to create queue subscriptions?

- With the current implementation, no manual subscription is needed for queue processing.
- `QUEUE_BACKEND=local`: worker polls the local sqlite queue table.
- `QUEUE_BACKEND=servicebus`: worker directly receives messages from a Service Bus **queue** using connection string + queue name.
- Service Bus **topics/subscriptions** are not used in this code path.

### How workers consume jobs

1. API receives `POST /ingestion/jobs`.
2. API creates a `queued` job row in `ingestion_jobs`.
3. API enqueues `{\"job_id\": \"...\"}`.
4. `worker.py` continuously reserves one message, marks job `running`, executes ingestion, then marks `succeeded` or `failed`.
5. You track status via `GET /ingestion/jobs/{job_id}`.

### Service Bus setup example (queue mode)

```bash
# create namespace
az servicebus namespace create \
  --resource-group <rg> \
  --name <sb-namespace> \
  --location <region> \
  --sku Standard

# create queue
az servicebus queue create \
  --resource-group <rg> \
  --namespace-name <sb-namespace> \
  --name ingestion-jobs

# get connection string
az servicebus namespace authorization-rule keys list \
  --resource-group <rg> \
  --namespace-name <sb-namespace> \
  --name RootManageSharedAccessKey \
  --query primaryConnectionString \
  -o tsv
```

Set in `.env`:

```bash
QUEUE_BACKEND=servicebus
AZURE_SERVICEBUS_CONNECTION_STRING=<value-from-cli>
AZURE_SERVICEBUS_QUEUE_NAME=ingestion-jobs
JOB_DB_PATH=data/jobs.db
```

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
