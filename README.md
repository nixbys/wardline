# Wardline

[![CI](https://github.com/nixbys/wardline/actions/workflows/ci.yml/badge.svg)](https://github.com/nixbys/wardline/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

Wardline is a research platform for lawful open-source intelligence. It answers natural-language questions with **cited answers** drawn from public, licensed or user-provided sources, and never states a claim it can't point to a source for.

- Hybrid retrieval: lexical, vector and knowledge-graph search, fused and reranked
- An agentic research mode that can compare evidence across two time periods
- Governance: roles, attribute-based access, an admin kill switch and an append-only audit log enforced by Postgres
- Engagement-gated connectors for authorized security assessments (Shodan, nmap, SpiderFoot)
- Free and open source: self-serve accounts with every feature, an admin [Ops Console](docs/guide.md#ops-console) and a public [Live Globe](docs/guide.md#live-globe)

## What this is not

Wardline does **not** intercept private communications, access systems without authorization, or do anything resembling mass surveillance. Those are crimes almost everywhere, and they are out of scope by design, not features left for later. Connectors that look up a specific target (exposure search, network scans) run only inside an active, target-scoped engagement; see [Authorized pentesting connectors](docs/guide.md#authorized-pentesting-connectors).

## Architecture

Seven planes:

| Plane | Where it lives | What it does |
|---|---|---|
| Collection | `src/wardline/connectors/` | Wikipedia, Wikidata, SEC EDGAR, OpenCorporates, archive.org (Wayback Machine), USGS earthquakes, NASA FIRMS fire detections, user upload, and a robots.txt-respecting web crawler — all behind one `Connector` interface (`base.py`), discoverable via a plugin registry (`registry.py`). Three more (Shodan, nmap, SpiderFoot) sit behind engagement-scoping — see [Authorized pentesting connectors](docs/guide.md#authorized-pentesting-connectors) |
| Ingestion & processing | `src/wardline/ingestion/` | HTML/PDF/OCR extraction, language detection, PII tagging, quality gates (quarantine on failure), structural chunking |
| Storage lakehouse | `src/wardline/storage/` | Postgres (documents/chunks/entities/edges/governance), MinIO/S3 for bronze-tier raw bytes, Alembic migrations |
| Retrieval substrate | `src/wardline/retrieval/` | Postgres `tsvector` lexical search (or real OpenSearch BM25, `LEXICAL_BACKEND=opensearch`) + `pgvector` HNSW semantic search, fused with Reciprocal Rank Fusion, reranked with a local cross-encoder, with a bounded-date-range filter (`published_after`/`published_before`) and an opt-in feedback-driven trust adjustment (`retrieval/feedback_signal.py`, off by default) |
| Knowledge & fusion | `src/wardline/graph/` | spaCy NER, rule-based relation extraction, entity resolution (blocking → scoring → clustering → human review), Neo4j, with an opt-in active-learning pass that trains match weights from real human review decisions (`graph/entity_resolution/splink_batch.py`, off by default) |
| Query plane | `src/wardline/query/`, `src/wardline/agent/` | The RAG pipeline (`query/pipeline.py`) and the bounded agentic research loop (`agent/loop.py`), both citation-verified before returning; the research-mode agent can scope two differently-dated searches to answer "how did X change between A and B" questions |
| Governance & security | `src/wardline/governance/` | Bearer-token auth, RBAC + ABAC, engagement-scoping for dual-use connectors, an admin kill switch, and an append-only audit log enforced by a Postgres trigger (not just application code) — plus a mode-level coverage-gap report (`GET /v1/audit/coverage-gaps`) surfaced in the [Ops Console](docs/guide.md#ops-console) |

## Setup

Requires Docker (or Podman with the `docker-compose` external provider) and network access.

```bash
cp .env.example .env
./scripts/generate_secrets.sh    # prints API_KEY_PEPPER/PASSWORD_PEPPER/POSTGRES_PASSWORD/NEO4J_PASSWORD/S3_SECRET_KEY —
                                  # paste the values into .env (or a real secrets manager, see below)
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml run --rm api python -m alembic upgrade head   # if not run automatically
docker compose -f docker/docker-compose.yml run --rm api python -m wardline.cli create-admin-user you@example.com
```

The last command prints an API key **once** — save it. Every API call other than `/healthz`/`/readyz` requires it (unless `AUTH_MODE=oidc`, see [Production readiness](docs/guide.md#production-readiness)).

By default, Postgres/Neo4j/MinIO's host ports are bound to `127.0.0.1` only (not `0.0.0.0`) — reachable from your machine for local `psql`/browser debugging, not from the network if this is ever run on a networked host. The `caddy` service (see [Production readiness](docs/guide.md#production-readiness)) TLS-terminates on 8080/8443 by default (rootless Docker/Podman can't bind 80/443 without a host-level capability grant — set `HTTP_PORT`/`HTTPS_PORT` in `.env` to use the standard ports on a root-daemon host) and reverse-proxies to `api:8000`; `api`'s own port stays published too for local-dev continuity with the plain-HTTP examples below.

## Quick start

With `KEY` set to the API key from `create-admin-user`, ingest a few Wikipedia pages and ask about them:

```bash
curl -X POST http://localhost:8000/v1/admin/connectors/wikipedia/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"titles": ["Airbnb", "Brian Chesky"]}}'

curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"question": "Who founded Airbnb?", "mode": "auto"}'
```

`mode` is `fast` (text only), `auto` (text and knowledge graph, the default) or `research` (a bounded multi-step agent). Without an LLM key, answers come from a deterministic extractive synthesizer; set `LLM_CLIENT_MODE=live`, `LLM_PROVIDER` and `LLM_API_KEY` in `.env` for model-written answers.

## Documentation

[docs/guide.md](docs/guide.md) covers the rest:

- [Using it](docs/guide.md#how-to-use-it): every connector, queries, the audit trail, entity review, admin controls
- [Adding a source](docs/guide.md#adding-a-new-source) and [authorized pentesting connectors](docs/guide.md#authorized-pentesting-connectors)
- [Accounts](docs/guide.md#self-serve-accounts), [donations](docs/guide.md#donations) and [governance](docs/guide.md#governance)
- [Testing](docs/guide.md#testing), [production readiness](docs/guide.md#production-readiness) and [design choices](docs/guide.md#design-choices)

Deployment notes live in [docs/](docs/): post-quantum TLS ([DEPLOYMENT_PQC.md](docs/DEPLOYMENT_PQC.md)) and Vercel ([VERCEL_DEPLOYMENT.md](docs/VERCEL_DEPLOYMENT.md)).

## The legal boundary

Building the *literal* fictional device this project translates from would mean mass interception of communications and unauthorized computer access — crimes in essentially every jurisdiction (wiretapping/interception statutes, computer-misuse law, data-protection law like GDPR). This is not a corner that was cut; it's the wall the design stops at. Everything in this repository operates over public, licensed, or user-provided data, with an audit trail, revocable access, a kill switch, and (for anything shaped like target reconnaissance) mandatory engagement scoping — the lawful capabilities are the whole point, and the boundary is enforced by refusing to build the rest, not by a configuration flag.

## Contributing, security and license

Contributions are welcome: connectors, governance primitives, fixes and docs. See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup and checks, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

Licensed under [Apache 2.0](LICENSE), which includes a patent grant. Third-party credits are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
