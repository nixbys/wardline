# Deploying wardline's backend to Vercel

Tracked (not one of this repo's untracked internal-planning docs -- this is operational deployment documentation for anyone running wardline on Vercel, same as README's own Setup section). Covers what a normal `docker compose up` deployment doesn't need to think about at all.

## The short version

wardline's backend is a FastAPI app with a real dependency footprint (torch via `sentence-transformers`/`faster-whisper`, `spacy`) and a stateful topology (Postgres+pgvector, Neo4j, object storage, a persistent worker process) that doesn't fit Vercel's stateless-function model by default. None of that makes it impossible -- every piece below either already has a config-only path to a managed equivalent, or a small serverless-shaped adapter (`api/routers/cron.py`). It does mean a Vercel deployment needs several external accounts and a couple of settings a docker-compose deployment never touches.

## 1. Bundle size -- two required Vercel project environment variables

`pip install torch` on Linux resolves the CUDA-bundled wheel by default (several GB of `nvidia-*` packages) even though Vercel's build has no GPU. The obvious-looking fixes for this **do not work against Vercel's real build** -- confirmed directly from an actual build log, not assumed:

- A root `requirements.txt` pointing pip at torch's CPU-only index goes completely unused -- Vercel's Python builder installs straight from `pyproject.toml` via `uv` ("Installing required dependencies from pyproject.toml..." in the build log), and never reads `requirements.txt` at all despite that being what Vercel's own FastAPI docs describe for *local* `vercel dev`.
- `pyproject.toml`'s `[tool.uv.sources]`/`[[tool.uv.index]]` (uv's own documented mechanism for pinning one package to an alternate index) also doesn't apply here -- confirmed empirically (installed it, checked, torch still resolved its default CUDA build) -- because that mechanism is project-mode-only (`uv sync`/`uv lock`), and Vercel's builder uses `uv pip install`, uv's separate pip-compatible interface, which doesn't read those sections.

**What actually works, verified directly**: two Vercel project environment variables (Project Settings → Environment Variables), which `uv pip install` *does* honor:

```
UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
UV_INDEX_STRATEGY=unsafe-best-match
```

With both set, `torch` resolves to `2.14.0+cpu` and the full project installs at **2.2GB total, zero `nvidia-*` packages** (without `UV_INDEX_STRATEGY=unsafe-best-match`, uv's default index strategy stops at the first index where it finds *any* matching version -- PyPI's CUDA-bundled one -- so both variables are needed together; either alone isn't sufficient). That's over Vercel's *standard* 500MB Python function limit, but comfortably under the 5GB **Large Functions** beta limit.

**You also need to enable Large Functions once**: add `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` as a third project environment variable. This works on any plan tier, including Hobby -- no upgrade needed for this part specifically.

## 2. Background jobs: Cron cadence is a real decision, not a detail

The self-hosted deployment runs a persistent `worker` process (`src/wardline/worker/main.py`): an infinite polling loop for ingestion jobs (2s interval) plus three periodic jobs (entity-resolution batch, Iceberg export, retrieval-feedback refresh) via APScheduler. Vercel Functions can't run anything long-lived like that.

`api/routers/cron.py` is the serverless-shaped replacement -- four `GET` endpoints (Vercel Cron always calls with `GET`), guarded by `CRON_SECRET`:

| Endpoint | Replaces |
|---|---|
| `GET /v1/cron/dispatch-jobs` | The ingestion-job polling loop -- claims and runs pending jobs until the queue is empty or `CRON_DISPATCH_BUDGET_SECONDS` is used up |
| `GET /v1/cron/entity-resolution` | The periodic entity-resolution batch (only runs if `ENTITY_RESOLUTION_BATCH_ENABLED=true`, same gate the worker uses) |
| `GET /v1/cron/iceberg-export` | The periodic Iceberg export (only runs if `ICEBERG_EXPORT_ENABLED=true`) |
| `GET /v1/cron/feedback-refresh` | The periodic retrieval-feedback refresh (always runs, matching the worker's own "always registered" behavior) |

`vercel.json`'s `crons` array wires these up. **This is where your Vercel plan tier matters directly**: Vercel Cron only allows **once-per-day** schedules on the Hobby plan; per-minute (or any sub-daily) schedules require Pro and fail to deploy at all on Hobby. `vercel.json` as shipped uses once-daily schedules (Hobby-safe) staggered a few hours apart. If you're on Pro and want closer-to-real-time job processing, tighten `dispatch-jobs`'s schedule (e.g. every few minutes) -- the endpoint itself already handles being called frequently (it's a no-op fast-return if the queue is empty).

**Live query answering (`POST /v1/query`) is unaffected either way** -- it's a synchronous request-response, not queue-driven. Only document ingestion, connector runs, and the three periodic jobs are subject to whatever cron cadence you configure.

`CRON_SECRET` is Vercel's own convention, not a custom header this app invented: set that exact env var name and Vercel automatically sends `Authorization: Bearer $CRON_SECRET` on every cron-triggered request. Leave it unset for a self-hosted deployment -- every `/v1/cron/*` route 404s (not 403 -- it doesn't even reveal it exists) until it's configured.

A job that's still `"running"` when a `dispatch-jobs` invocation gets killed for exceeding its time budget has no worker process to leave it for -- so `dispatch-jobs` reclaims (marks `"failed"`, with a clear cause) any job still `"running"` past `CRON_STALE_JOB_TIMEOUT_SECONDS` (default 900s) before claiming new work. This is a real, routine occurrence under this dispatch model, not an edge case -- see `worker/jobs.py:reap_stale_jobs`'s own docstring.

## 3. Managed infrastructure

All three of these are config-only -- nothing in the app's code assumes docker-compose specifically.

- **Postgres + pgvector**: `vercel install neon` provisions one from Vercel's own Marketplace (pgvector is a supported extension there; the migration that runs `CREATE EXTENSION IF NOT EXISTS vector` already works against it unchanged). Set `DATABASE_URL_OVERRIDE`/`DATABASE_URL_ASYNC_OVERRIDE` from the credentials Vercel injects. Any other pgvector-supporting managed Postgres works the same way.
- **Neo4j**: Neo4j Aura (not a Vercel Marketplace product -- provision it separately at [neo4j.com/aura](https://neo4j.com/cloud/aura)). Set `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`. No separate schema-setup step needed -- `api/main.py`'s FastAPI `lifespan` hook already calls `ensure_constraints()` on every cold start (idempotent `CREATE CONSTRAINT IF NOT EXISTS`), unlike Postgres below.
- **Object storage**: real AWS S3, or any S3-compatible provider (Cloudflare R2, etc.) -- `BLOB_BACKEND=s3` + `S3_ENDPOINT_URL`/`S3_ACCESS_KEY`/`S3_SECRET_KEY`/`S3_BUCKET`/`S3_REGION`, exactly the fields `.env.example` already documents.

Every other secret in `.env.example` (`LLM_API_KEY`, `STRIPE_*`, `OPENAI_API_KEY`, etc.) gets set the same way, as Vercel project environment variables.

## 4. Migrations: a deliberate manual step

Unlike Neo4j's constraints, Postgres migrations are **not** run automatically on deploy or cold start -- run `alembic upgrade head` manually (`DATABASE_URL_OVERRIDE=<your-neon-url> alembic upgrade head`, from your own machine or CI) before deploying code that depends on a schema change. This is the safer default: no surprise schema changes triggered by every build/cold start, and it avoids the classic ordering hazard of new code briefly running against an old schema (or vice versa) during a deploy. **Ordering rule for every future schema-changing deploy, not just initial setup: migrate first, deploy the code that depends on it second, never the other way round.**

## 5. Things that stay out of scope, on purpose

- **toolrunner/spiderfoot** (active-scanning connectors): already optional and URL-configured (`TOOLRUNNER_URL`, `SPIDERFOOT_URL`). nmap needs raw socket access a Vercel function doesn't grant, so these need to point at an externally-reachable instance (a small VPS, or your existing self-hosted stack, matching the same "cooperating deployment" pattern already built for sharing a SpiderFoot instance across projects) -- or stay unset, in which case those connectors are simply unavailable from this deployment, same as today when unconfigured.
- **OpenTelemetry export**: `configure_observability()` installs a `BatchSpanProcessor` with a background export thread at import time. On a freeze/thaw serverless runtime that thread can get frozen mid-export between invocations -- a known OTel-on-serverless limitation, not specific to this app. Expect occasional incomplete traces rather than a hard failure; not something this migration fixes.
