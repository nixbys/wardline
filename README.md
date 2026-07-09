# cranus

A lawful OSINT + AI research platform: hybrid retrieval-augmented generation (lexical + vector + knowledge graph) over public, licensed, or consented sources, with governance, an immutable audit log, and an agentic research mode.

This is the buildable translation of a fictional "omniscient" information engine (the report this repo was built from used *Hliðskjálf* from *The Irregular at Magic High School* as its reference point) into real, lawful architecture. It answers natural-language questions with **cited, verifiable answers**, never asserting a claim it can't point to a source for.

## What this is not

This project deliberately does **not** implement mass interception of private communications, unauthorized access to systems, or anything resembling SIGINT/XKeyScore-style surveillance. Those are illegal almost everywhere (wiretapping/interception law, computer-misuse law, data-protection law) and are not "features left for later" — they are out of scope by design. Everything here operates over sources that are public, licensed for reuse, or provided by the user themselves (upload).

## Architecture

Seven planes, matching the source report's design:

| Plane | Where it lives | What it does |
|---|---|---|
| Collection | `src/cranus/connectors/` | Wikipedia, SEC EDGAR, user upload, and a robots.txt-respecting web crawler — all behind one `Connector` interface (`base.py`), discoverable via a plugin registry (`registry.py`) |
| Ingestion & processing | `src/cranus/ingestion/` | HTML/PDF/OCR extraction, language detection, PII tagging, quality gates (quarantine on failure), structural chunking |
| Storage lakehouse | `src/cranus/storage/` | Postgres (documents/chunks/entities/edges/governance), MinIO/S3 for bronze-tier raw bytes, Alembic migrations |
| Retrieval substrate | `src/cranus/retrieval/` | Postgres `tsvector` lexical search + `pgvector` HNSW semantic search, fused with Reciprocal Rank Fusion, reranked with a local cross-encoder |
| Knowledge & fusion | `src/cranus/graph/` | spaCy NER, rule-based relation extraction, entity resolution (blocking → scoring → clustering → human review), Neo4j |
| Query plane | `src/cranus/query/`, `src/cranus/agent/` | The RAG pipeline (`query/pipeline.py`) and the bounded agentic research loop (`agent/loop.py`), both citation-verified before returning |
| Governance & security | `src/cranus/governance/` | Bearer-token auth, RBAC + ABAC, an admin kill switch, and an append-only audit log enforced by a Postgres trigger (not just application code) |

## Setup

Requires Docker (or Podman with the `docker-compose` external provider) and network access.

```bash
cp .env.example .env          # edit API_KEY_PEPPER at minimum before any real deployment
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml run --rm migrator   # if not run automatically
docker compose -f docker/docker-compose.yml run --rm api python -m cranus.cli create-admin-user you@example.com
```

The last command prints an API key **once** — save it. Every API call other than `/healthz`/`/readyz` requires it:

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"question": "Who founded Airbnb?", "mode": "auto"}'
```

`mode` is `"fast"` (text-only), `"auto"` (text + knowledge graph, default), or `"research"` (bounded multi-step agent).

By default the query/agent planes run against `LLM_CLIENT_MODE=mock` — a deterministic, no-network synthesizer that does real extractive work over whatever retrieval actually finds (so the whole pipeline is exercisable without an API key). Set `LLM_CLIENT_MODE=live` and `ANTHROPIC_API_KEY` in `.env` for genuine grounded synthesis from Claude.

### Ingesting your first corpus

```bash
curl -X POST http://localhost:8000/v1/admin/connectors/wikipedia/run \
  -H "Authorization: Bearer <key>" -H "Content-Type: application/json" \
  -d '{"params": {"titles": ["Airbnb", "Brian Chesky", "Joe Gebbia", "Nathan Blecharczyk"]}}'
```

This queues a job the `worker` container picks up: fetch → parse → chunk → embed → index → NER/relation-extraction → entity resolution → Neo4j sync. Or upload your own document directly:

```bash
curl -X POST http://localhost:8000/v1/documents/upload \
  -H "Authorization: Bearer <key>" -F "file=@report.pdf"
```

## Adding a new source

Implement `Connector` (`src/cranus/connectors/base.py`: `discover()`, `fetch()`, `parse()`, `provenance()`), decorate the class with `@register_connector("your-name")`, and either add it to `connectors/registry.py`'s built-in import list, or ship it as a separate installable package that declares a `cranus.connectors` entry point — no change to this repo required for the latter. It's then immediately usable via `POST /v1/admin/connectors/{name}/run`.

## Governance

- **Roles**: `viewer` (query only), `analyst` (+ trigger ingestion, review entity merges), `admin` (+ manage users, kill switch).
- **Kill switch**: `POST /v1/admin/kill-switch {"enabled": true}` freezes `/v1/query` for everyone (503) without locking admins out of the admin surface itself — the toggle endpoint is deliberately *not* gated by the switch it controls.
- **Audit log**: every query (and every agent tool call) is written to `audit_events` before and after execution. The table has a `BEFORE UPDATE OR DELETE` trigger that unconditionally raises — this is enforced by Postgres itself, not application discipline (a plain `REVOKE` doesn't work here: table owners keep full privileges regardless of `GRANT`/`REVOKE`).

## Testing

```bash
docker compose -f docker/docker-compose.yml run --rm api python -m pytest tests/unit -v
```

42 unit tests cover chunking (offsets, overlap, the oversized-line hard-split path), RRF fusion, entity-resolution scoring/blocking/clustering, citation verification, quality gates, RBAC/ABAC, API-key hashing, agent guardrails, and a schema-drift contract test against the report's data models.

Everything else in this README was verified **live** against real Postgres/Neo4j/MinIO during development: real Wikipedia ingestion end-to-end, hybrid retrieval producing sensible rankings, a knowledge-graph fact (`Gebbia FOUNDED Airbnb`) correctly cited in a `mode="auto"` answer, a real 3-step agent trajectory in `mode="research"`, and the full governance flow (auth → RBAC → revocation → kill switch, including a lockout bug found and fixed — see git history for the details of every bug found and fixed during that testing, phase by phase). Integration tests against real Postgres/Neo4j via `testcontainers-python` are the natural next addition but aren't included yet.

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

## The legal boundary

Building the *literal* fictional device this project translates from would mean mass interception of communications and unauthorized computer access — crimes in essentially every jurisdiction (wiretapping/interception statutes, computer-misuse law, data-protection law like GDPR). This is not a corner that was cut; it's the wall the design stops at. Everything in this repository operates over public, licensed, or user-provided data, with an audit trail, revocable access, and a kill switch — the lawful capabilities are the whole point, and the boundary is enforced by refusing to build the rest, not by a configuration flag.
