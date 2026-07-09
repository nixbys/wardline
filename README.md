# cranus

A lawful OSINT + AI research platform: hybrid retrieval-augmented generation (lexical + vector + knowledge graph) over public, licensed, or consented sources, with governance, an immutable audit log, and an agentic research mode.

This is the buildable translation of a fictional "omniscient" information engine (the report this repo was built from used *Hliðskjálf* from *The Irregular at Magic High School* as its reference point) into real, lawful architecture. It answers natural-language questions with **cited, verifiable answers**, never asserting a claim it can't point to a source for.

## What this is not

This project deliberately does **not** implement mass interception of private communications, unauthorized access to systems, or anything resembling SIGINT/XKeyScore-style surveillance. Those are illegal almost everywhere (wiretapping/interception law, computer-misuse law, data-protection law) and are not "features left for later" — they are out of scope by design. Everything here operates over sources that are public, licensed for reuse, or provided by the user themselves (upload).

This also means a category of *dual-use* connectors (Shodan/Censys-style exposure search, breach-check APIs, SpiderFoot-style aggregators) is treated differently from ordinary public-corpus sources: see [Engagement scoping](#engagement-scoping-for-dual-use-connectors) below. None are integrated yet, but the governance primitive they'd need to be added responsibly already exists.

## Architecture

Seven planes, matching the source report's design:

| Plane | Where it lives | What it does |
|---|---|---|
| Collection | `src/cranus/connectors/` | Wikipedia, Wikidata, SEC EDGAR, OpenCorporates, archive.org (Wayback Machine), user upload, and a robots.txt-respecting web crawler — all behind one `Connector` interface (`base.py`), discoverable via a plugin registry (`registry.py`) |
| Ingestion & processing | `src/cranus/ingestion/` | HTML/PDF/OCR extraction, language detection, PII tagging, quality gates (quarantine on failure), structural chunking |
| Storage lakehouse | `src/cranus/storage/` | Postgres (documents/chunks/entities/edges/governance), MinIO/S3 for bronze-tier raw bytes, Alembic migrations |
| Retrieval substrate | `src/cranus/retrieval/` | Postgres `tsvector` lexical search + `pgvector` HNSW semantic search, fused with Reciprocal Rank Fusion, reranked with a local cross-encoder |
| Knowledge & fusion | `src/cranus/graph/` | spaCy NER, rule-based relation extraction, entity resolution (blocking → scoring → clustering → human review), Neo4j |
| Query plane | `src/cranus/query/`, `src/cranus/agent/` | The RAG pipeline (`query/pipeline.py`) and the bounded agentic research loop (`agent/loop.py`), both citation-verified before returning |
| Governance & security | `src/cranus/governance/` | Bearer-token auth, RBAC + ABAC, engagement-scoping for dual-use connectors, an admin kill switch, and an append-only audit log enforced by a Postgres trigger (not just application code) |

## Setup

Requires Docker (or Podman with the `docker-compose` external provider) and network access.

```bash
cp .env.example .env          # edit API_KEY_PEPPER at minimum before any real deployment
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml run --rm api python -m alembic upgrade head   # if not run automatically
docker compose -f docker/docker-compose.yml run --rm api python -m cranus.cli create-admin-user you@example.com
```

The last command prints an API key **once** — save it. Every API call other than `/healthz`/`/readyz` requires it.

By default, Postgres/Neo4j/MinIO's host ports are bound to `127.0.0.1` only (not `0.0.0.0`) — reachable from your machine for local `psql`/browser debugging, not from the network if this is ever run on a networked host. Only the `api` service's port (8000) is published broadly, and even that should sit behind a TLS-terminating reverse proxy in any real deployment (see [Production readiness](#production-readiness)).

## How to use it

This walks through the full loop: standing up the stack, ingesting from each connector, querying, reviewing entity merges, and the admin controls. All examples assume `KEY` holds the API key from `create-admin-user` above.

### 1. Ingest something

Every connector is triggered the same way: `POST /v1/admin/connectors/{name}/run`, which queues a job the `worker` container picks up (fetch → parse → chunk → embed → index → NER/relation-extraction → entity resolution → Neo4j sync).

```bash
# Wikipedia — prose, good general coverage
curl -X POST http://localhost:8000/v1/admin/connectors/wikipedia/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"titles": ["Airbnb", "Brian Chesky", "Joe Gebbia", "Nathan Blecharczyk"]}}'

# Wikidata — structured facts (CC0), feeds the knowledge graph more reliably than free-text NER
curl -X POST http://localhost:8000/v1/admin/connectors/wikidata/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"ids": ["Q63327"]}}'

# archive.org — historical snapshots of a page, for point-in-time citations
curl -X POST http://localhost:8000/v1/admin/connectors/archive_org/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"urls": ["https://en.wikipedia.org/wiki/Airbnb"], "limit": 5}}'

# SEC EDGAR — US public-company filings (ciks is a list; Airbnb's CIK is 0001559720)
curl -X POST http://localhost:8000/v1/admin/connectors/sec_edgar/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"ciks": ["0001559720"], "forms": ["10-K"]}}'

# OpenCorporates — company registry data outside SEC EDGAR's US-filer scope.
# Requires OPENCORPORATES_API_TOKEN set in .env first (every endpoint needs one now).
curl -X POST http://localhost:8000/v1/admin/connectors/opencorporates/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"search": "Airbnb"}}'

# web_crawler — autonomous, robots.txt-respecting crawl from seed URLs
curl -X POST http://localhost:8000/v1/admin/connectors/web_crawler/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"seeds": ["https://example.com"], "max_depth": 1, "max_pages": 10}}'
```

Or upload your own document directly (bypasses `discover()`, bounded by `UPLOAD_MAX_BYTES`, 50 MiB by default):

```bash
curl -X POST http://localhost:8000/v1/documents/upload \
  -H "Authorization: Bearer $KEY" -F "file=@report.pdf"
```

Check a job's status:

```bash
curl http://localhost:8000/v1/admin/connectors/jobs/{job_id} -H "Authorization: Bearer $KEY"
```

### 2. Ask a question

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"question": "Who founded Airbnb?", "mode": "auto"}'
```

`mode` is `"fast"` (text-only retrieval), `"auto"` (text + knowledge graph, default), or `"research"` (bounded multi-step agent — decomposes the question, calls retrieval/graph tools iteratively up to a step/token budget, and requires every claim in its final answer to carry a citation before returning).

By default the query/agent planes run against `LLM_CLIENT_MODE=mock` — a deterministic, no-network synthesizer that does real extractive work over whatever retrieval actually finds (so the whole pipeline is exercisable without an API key). Set `LLM_CLIENT_MODE=live` and `ANTHROPIC_API_KEY` in `.env` for genuine grounded synthesis from Claude.

### 3. Inspect what happened

```bash
# The session this query created, including retrieved sources
curl http://localhost:8000/v1/session/{session_id} -H "Authorization: Bearer $KEY"

# The full audit trail (every query and every agent tool call)
curl http://localhost:8000/v1/audit -H "Authorization: Bearer $KEY"

# Leave feedback on an answer (integer rating + optional comment)
curl -X POST http://localhost:8000/v1/feedback \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"session_id": "...", "rating": 1, "comment": "correct and well-cited"}'
```

### 4. Review entity merges

Entity resolution auto-merges only high-confidence matches; ambiguous ones (e.g. "Nathan Blecharczyk" vs. a fuzzy alias) queue for human review instead of silently merging or silently staying split.

```bash
curl http://localhost:8000/v1/admin/entity-review/queue -H "Authorization: Bearer $KEY"
curl -X POST http://localhost:8000/v1/admin/entity-review/{review_id}/decision \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"decision": "merged"}'   # or "rejected"
```

### 5. Admin controls

```bash
# Create a user with a role (admin | analyst | viewer)
curl -X POST http://localhost:8000/v1/admin/users \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"email": "analyst@example.com", "role": "analyst"}'

# Revoke access
curl -X POST http://localhost:8000/v1/admin/users/{user_id}/revoke -H "Authorization: Bearer $KEY"

# Kill switch: freezes /v1/query for everyone without locking admins out of /v1/admin/*
curl -X POST http://localhost:8000/v1/admin/kill-switch \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{"enabled": true}'
```

### 6. Engagement scoping (for dual-use connectors)

See the section below — there's nothing to run here yet since no dual-use connector is integrated, but the admin surface exists:

```bash
curl -X POST http://localhost:8000/v1/admin/engagements \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"target": "example.com", "scope_note": "authorized external footprint assessment", "evidence_ref": "SOW-2026-001", "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2026-02-01T00:00:00Z"}'
```

## Adding a new source

Implement `Connector` (`src/cranus/connectors/base.py`: `discover()`, `fetch()`, `parse()`, `provenance()`), decorate the class with `@register_connector("your-name")`, and either add it to `connectors/registry.py`'s built-in import list, or ship it as a separate installable package that declares a `cranus.connectors` entry point — no change to this repo required for the latter. Add its `default_license` tag to `ingestion/quality_gates.KNOWN_LICENSES` or every document it ingests will be quarantined. It's then immediately usable via `POST /v1/admin/connectors/{name}/run`.

If your connector performs a target-lookup (not a fixed public corpus — think "look up everything about domain X" rather than "fetch Wikipedia page Y"), set `requires_engagement = True` (see next section) before wiring it in.

## Engagement scoping (for dual-use connectors)

RBAC answers "who are you." ABAC answers "what license does this document carry." Neither answers "who authorized looking at *this specific target* with a tool that's shaped like reconnaissance" — which matters for connectors like Shodan/Censys (internet-wide exposure search), breach-check APIs, or SpiderFoot-style aggregators. Those are legitimate for *authorized* security assessments, but a general-purpose "look up anything about anyone" connector built on top of them is a different, riskier product than the encyclopedic/registry sources above.

`src/cranus/storage/models/engagements.py` + `governance/engagements.py` + `governance/pep.py:enforce_engagement_scope` implement the missing primitive: an `Engagement` records a target, a scope note, a reference to the authorization evidence (a signed SOW, a ticket), and a validity window. Any connector with `requires_engagement = True` cannot run without an active, non-expired, non-revoked engagement whose target covers the requested lookup (`POST /v1/admin/connectors/{name}/run` then requires `params.target` and `engagement_id`).

**No connector currently sets `requires_engagement = True`** — this lands the scaffolding, not a new dual-use source. Adding one is a deliberate decision, not a drop-in.

## Governance

- **Roles**: `viewer` (query only), `analyst` (+ trigger ingestion, review entity merges), `admin` (+ manage users, kill switch, create engagements).
- **Kill switch**: `POST /v1/admin/kill-switch {"enabled": true}` freezes `/v1/query` for everyone (503) without locking admins out of the admin surface itself — the toggle endpoint is deliberately *not* gated by the switch it controls.
- **Engagement scoping**: see above.
- **Audit log**: every query (and every agent tool call) is written to `audit_events` before and after execution. The table has a `BEFORE UPDATE OR DELETE` trigger that unconditionally raises — this is enforced by Postgres itself, not application discipline (a plain `REVOKE` doesn't work here: table owners keep full privileges regardless of `GRANT`/`REVOKE`).

## Testing

```bash
docker compose -f docker/docker-compose.yml run --rm api python -m pytest tests/unit -v
```

55 unit tests cover chunking (offsets, overlap, the oversized-line hard-split path), RRF fusion, entity-resolution scoring/blocking/clustering, citation verification, quality gates, RBAC/ABAC, engagement target-scope matching and validity-window logic, API-key hashing, agent guardrails, and a schema-drift contract test against the report's data models.

Everything else in this README was verified **live** against real Postgres/Neo4j/MinIO during development — real ingestion end-to-end from every connector, hybrid retrieval producing sensible rankings, real knowledge-graph facts (e.g. `Chesky FOUNDED Airbnb`) correctly cited in `mode="auto"` answers, a real multi-step agent trajectory in `mode="research"`, and the full governance flow (auth → RBAC → revocation → kill switch → engagement scoping). See `git log` for the specifics of every bug found and fixed during that testing, phase by phase — commit messages document root cause and how each was verified fixed, not just what changed.

CI (`.github/workflows/ci.yml`) runs the same unit tests against real Postgres/Neo4j service containers on every push/PR, plus lint (`ruff`) and a Docker build check. See `CONTRIBUTING.md` for local dev workflow and PR conventions.

Integration tests against real Postgres/Neo4j via `testcontainers-python` are the natural next addition but aren't included yet.

## Production readiness

This is a lean single-node build (see "Scope reductions" below) with a genuine hardening pass, not a fully production-hardened deployment. What's covered vs. what's still your responsibility before running this with real data or real users:

**Already in place:**
- Non-root users in both container images (`docker/Dockerfile.api`, `docker/Dockerfile.worker`).
- `.dockerignore` keeps `.env`, `.git`, and local caches out of the build context.
- Postgres/Neo4j/MinIO host ports bound to `127.0.0.1` only; only `api` (8000) is broadly published.
- Security response headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control: no-store`) on every response.
- `debug=False` set explicitly on the FastAPI app, plus a catch-all exception handler that logs full detail server-side (structured, via `structlog`) but returns only a generic message to clients — no stack traces leak over the wire.
- Bounded-read upload size limit (`UPLOAD_MAX_BYTES`), immutable audit log, RBAC/ABAC, per-key rate limiting (`slowapi`), argon2-hashed API keys.

**Still your responsibility before real production use:**
- **Secrets**: `API_KEY_PEPPER` and the Postgres/Neo4j/MinIO credentials in `docker-compose.yml`/`.env` are dev-grade defaults. Rotate all of them and pull from a real secrets manager (Vault, AWS/GCP secret manager, etc.), not `.env` files on disk.
- **TLS**: uvicorn is served plaintext on 8000. Put a TLS-terminating reverse proxy (nginx, Caddy, an ALB) in front before exposing this beyond localhost.
- **Enterprise IAM**: bearer API keys are the whole auth model here. Swap for a real IdP (OIDC/SAML) and MFA before onboarding real users, per the report's own recommendation.
- **Dependency pinning**: `pyproject.toml` uses floating minimum versions (`>=`), no lockfile. Generate and commit one (`pip freeze`, or migrate to `uv`/`poetry`) before treating builds as reproducible.
- **Backups**: no backup/restore strategy is defined for the `pgdata`/`neo4j_data`/`minio_data` volumes. Add one before storing anything you can't afford to lose.
- **Resource limits**: `docker-compose.yml` has no CPU/memory limits on any service — add them (`deploy.resources` or `mem_limit`/`cpus`) before running alongside other workloads.
- **Observability**: OTel is console-exporter-only by default (`OTEL_EXPORTER_OTLP_ENDPOINT` unset). Point it at a real collector before relying on it for incident response.

## Scope reductions vs. the source report

The report this was built from sketches a larger platform than a single build session can responsibly implement in full. These substitutions are deliberate, not oversights:

| Report's ideal | This build | Why proportionate here |
|---|---|---|
| Kafka streaming bus | Postgres `SELECT ... FOR UPDATE SKIP LOCKED` job queue | A handful of slow-moving connectors don't need a streaming bus |
| Airflow/Prefect/Dagster | A worker polling loop + `ingestion_jobs` table | Ingestion is a linear per-document pipeline, not a fan-out DAG |
| Iceberg/Delta over object storage | Plain Postgres tables + MinIO for raw bytes only | No big-data-scale analytics requiring time-travel/schema evolution |
| OpenSearch (true BM25) | Postgres `tsvector`/`ts_rank_cd` (BM25-*like*) | Avoids a second search engine; ParadeDB `pg_search` is the noted upgrade path |
| Full ASR pipeline | Not implemented | No audio/video connectors in scope |
| Cloud/commercial OCR | Local Tesseract | Adequate for typed/scanned filings, not handwriting |
| Enterprise IAM (OIDC/MFA, Vault/KMS) | Bearer API keys + `.env` secrets | Single-node app — swap for a real IdP/KMS before real production use |
| Splink/Dedupe entity resolution | Homemade blocking (metaphone) + scoring (rapidfuzz/jaro-winkler) + clustering (connected components) | Splink is the noted upgrade path if accuracy needs to scale |
| Dependency-parse relation extraction | Sentence-scoped keyword-trigger rules | Real, but coarser than true NLP relation extraction — produces some false positives (documented, not hidden) |
| Pinned/locked dependencies | Floating `>=` minimum versions, no lockfile | Acceptable for active development; generate a lockfile before treating builds as reproducible |

## The legal boundary

Building the *literal* fictional device this project translates from would mean mass interception of communications and unauthorized computer access — crimes in essentially every jurisdiction (wiretapping/interception statutes, computer-misuse law, data-protection law like GDPR). This is not a corner that was cut; it's the wall the design stops at. Everything in this repository operates over public, licensed, or user-provided data, with an audit trail, revocable access, a kill switch, and (for anything shaped like target reconnaissance) mandatory engagement scoping — the lawful capabilities are the whole point, and the boundary is enforced by refusing to build the rest, not by a configuration flag.

## Contributing

See `CONTRIBUTING.md` for dev setup, test/lint commands, and PR conventions. `CHANGELOG.md` tracks notable changes.
