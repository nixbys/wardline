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
cp .env.example .env
./scripts/generate_secrets.sh    # prints API_KEY_PEPPER/POSTGRES_PASSWORD/NEO4J_PASSWORD/S3_SECRET_KEY —
                                  # paste the values into .env (or a real secrets manager, see below)
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml run --rm api python -m alembic upgrade head   # if not run automatically
docker compose -f docker/docker-compose.yml run --rm api python -m cranus.cli create-admin-user you@example.com
```

The last command prints an API key **once** — save it. Every API call other than `/healthz`/`/readyz` requires it (unless `AUTH_MODE=oidc`, see [Production readiness](#production-readiness)).

By default, Postgres/Neo4j/MinIO's host ports are bound to `127.0.0.1` only (not `0.0.0.0`) — reachable from your machine for local `psql`/browser debugging, not from the network if this is ever run on a networked host. The `caddy` service (see [Production readiness](#production-readiness)) TLS-terminates on 8080/8443 by default (rootless Docker/Podman can't bind 80/443 without a host-level capability grant — set `HTTP_PORT`/`HTTPS_PORT` in `.env` to use the standard ports on a root-daemon host) and reverse-proxies to `api:8000`; `api`'s own port stays published too for local-dev continuity with the plain-HTTP examples below.

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

# On-demand Splink batch dedupe pass (also runs on entity_resolution_batch_interval_seconds,
# default 6h — see "Scope reductions" below). Admin-only: can merge outright above the
# high-confidence threshold, not just queue for review.
curl -X POST "http://localhost:8000/v1/admin/entity-review/batch-resolve?entity_type=Person" \
  -H "Authorization: Bearer $KEY"
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

This is a lean single-node build (see "Scope reductions" below). Every item below is now actually implemented, not just documented as a gap — but each still needs *your* infrastructure/configuration to be real production-grade, since none of that (a real domain, a real IdP, a real secrets manager, a real off-host backup target) can be conjured up by this repo on its own.

- **Secrets**: `Settings` (`common/config.py`) reads `secrets_dir="/run/secrets"` when that path exists — mount a Docker secret, Kubernetes Secret volume, or Vault-agent-rendered file there (named after the field, e.g. `/run/secrets/api_key_pepper`) and it wins over the plain env var. `scripts/generate_secrets.sh` generates strong values for first-time setup. `docker-compose.yml`'s Postgres/Neo4j/MinIO credentials are now sourced from the same `.env` variables the app itself uses (`POSTGRES_PASSWORD`, `NEO4J_PASSWORD`, `S3_SECRET_KEY`) instead of being independently hardcoded, so there's one place to change a credential, not two that can drift. You still need to actually deploy a secrets manager and rotate the shipped dev defaults — this just means there's a real integration point once you do.
- **TLS**: a `caddy` service reverse-proxies `api:8000` and terminates TLS, published on `HTTP_PORT`/`HTTPS_PORT` (default 8080/8443 — rootless Docker/Podman can't bind 80/443 without a host capability grant; set both to 80/443 in `.env` on a root-daemon host). Set `DOMAIN=yourhost.example.com` and point DNS at this host — Caddy automatically provisions and renews a real Let's Encrypt certificate, no other config change needed. Without `DOMAIN` set, it serves HTTPS on `localhost` using Caddy's own locally-trusted CA (fine for local testing; browsers/`curl` need `-k` or to trust that CA).
- **Enterprise IAM**: set `AUTH_MODE=oidc` (+ `OIDC_ISSUER`, `OIDC_JWKS_URL`, optionally `OIDC_AUDIENCE`/`OIDC_ROLE_CLAIM`) to validate bearer tokens against any real OIDC-compliant IdP (Okta, Auth0, Keycloak, Entra ID) instead of this project's own API-key system — see `api/oidc_auth.py`/`api/deps.py`. A user record is created/kept in sync locally on first sight (for revocation and audit-log foreign keys), with the IdP as the source of truth for role assignment. **Not yet live-tested against a real IdP** — validated by code review and the JWT/JWKS-handling logic only, since no IdP is available in this dev environment.
- **Dependency pinning**: `requirements-lock.txt` (generated via `pip freeze` inside the built image, see `scripts/regenerate_lockfile.sh`) pins every transitive dependency to an exact version. `pyproject.toml` keeps floating `>=` bounds for flexibility when adding new dependencies; the lockfile is what real deployments should actually install from for reproducible builds.
- **Backups**: `scripts/backup.sh`/`scripts/restore.sh` dump Postgres (`pg_dump`, online), Neo4j (`neo4j-admin dump`, brief downtime — Community Edition has no hot-backup path), and MinIO (`mc mirror`) into `backups/<timestamp>/`. **Not exercised against a full stop/restore cycle this session** — reviewed for correctness, not live-run, since doing so against this environment's real ingested data risked actual data loss if something in the exact `neo4j-admin` CLI flags for this image version were wrong. Test a full backup→restore cycle in a disposable environment before relying on it. You still need to copy the output off-host — a backup on the same disk isn't a backup.
- **Resource limits**: every `docker-compose.yml` service now sets `mem_limit`/`cpus` (api/worker: 2 GiB/2 CPU each, for the ML models loaded at runtime; neo4j: 2 GiB; postgres: 1 GiB; the rest smaller). These are starting points sized for a single small deployment — profile and adjust for your actual traffic/hardware.
- **Observability**: `/metrics` (Prometheus, via `prometheus-fastapi-instrumentator`) and OpenTelemetry tracing (via `opentelemetry-instrumentation-fastapi`) are both wired into the app now, not just declared as dependencies. Traces print to console by default; set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317` to route through the bundled `otel-collector` compose service, and edit `docker/otel-collector-config.yaml` to add a real backend exporter (Honeycomb, Grafana Cloud, Datadog, etc.) — it only logs to its own stdout by default.

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
| Enterprise IAM (OIDC/MFA, Vault/KMS) | Optional OIDC JWT auth mode (see Production readiness) alongside the default API-key system | OIDC path exists but isn't live-tested against a real IdP; MFA is the IdP's responsibility, not this app's |
| ~~Splink/Dedupe entity resolution~~ **Implemented (batch)** | The incremental per-mention resolver (blocking/scoring/clustering) still runs at ingestion time — real-time EM training isn't a thing — but a periodic Splink batch pass (`graph/entity_resolution/splink_batch.py`, every `entity_resolution_batch_interval_seconds`, default 6h) now re-examines each entity type with a real DuckDB-backed Fellegi-Sunter comparison engine and merges/queues through the same governance thresholds | Closed for the complementary batch-reconciliation role Splink actually fits; see the module docstring for why match weights are set explicitly rather than EM-trained (small-sample instability) and how to switch to EM once a type has real volume |
| ~~Dependency-parse relation extraction~~ **Implemented** | spaCy dependency-tree walk (nsubj/nsubjpass/agent/dobj, `conj` coordination, relative-clause antecedents) from trigger tokens, not a keyword-only sentence match | Closed — see `graph/relation_extraction.py`; a narrowly-scoped single-candidate fallback covers the small model's occasional mis-parse of hyphenated "co-founded" without reintroducing the old cartesian-product false positives |

## The legal boundary

Building the *literal* fictional device this project translates from would mean mass interception of communications and unauthorized computer access — crimes in essentially every jurisdiction (wiretapping/interception statutes, computer-misuse law, data-protection law like GDPR). This is not a corner that was cut; it's the wall the design stops at. Everything in this repository operates over public, licensed, or user-provided data, with an audit trail, revocable access, a kill switch, and (for anything shaped like target reconnaissance) mandatory engagement scoping — the lawful capabilities are the whole point, and the boundary is enforced by refusing to build the rest, not by a configuration flag.

## Contributing

See `CONTRIBUTING.md` for dev setup, test/lint commands, and PR conventions. `CHANGELOG.md` tracks notable changes.
