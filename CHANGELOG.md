# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project doesn't yet cut tagged
releases, so entries are grouped by work session instead of version number.

## [Unreleased]

### Added
- Production hardening: non-root container users, `.dockerignore`, security response headers,
  an explicit unhandled-exception handler that logs full detail server-side but never leaks it to
  clients, a bounded-read upload size limit (`UPLOAD_MAX_BYTES`, default 50 MiB), and
  localhost-only host-port binding for Postgres/Neo4j/MinIO in `docker-compose.yml`.
- CI (`.github/workflows/ci.yml`): lint (ruff), unit tests against real Postgres/Neo4j service
  containers, and a Docker build check.
- `CONTRIBUTING.md`.
- Engagement-scoping governance model (`engagements` table, `governance/engagements.py`,
  `pep.enforce_engagement_scope`, `POST/GET /v1/admin/engagements`): the missing primitive for any
  future dual-use, target-lookup connector (Shodan/Censys-style exposure search, breach-check APIs,
  SpiderFoot-style aggregators) — RBAC says who you are, ABAC says what license a document carries,
  neither says who authorized looking at *this specific target*. No connector uses it yet; it's
  scaffolding for if/when one is added, gated by `Connector.requires_engagement`.
- `wikidata` connector: renders bounded, research-relevant Wikidata statements (founded, CEO,
  parent-org, headquarters) into declarative sentences that flow through the existing
  ingestion/NER/relation-extraction pipeline. CC0 licensed.
- `opencorporates` connector: company-registry data beyond SEC EDGAR's US-filer scope. Requires an
  operator-supplied `OPENCORPORATES_API_TOKEN` (OpenCorporates now gates every endpoint on one).
- `archive_org` connector: Wayback Machine snapshots via the public CDX API, for point-in-time
  citations and recovering since-changed/removed sources.
- `connectors/config.py`: resolves per-connector runtime config from `Settings`.

### Fixed
- `admin_connectors.run_connector` could 500 on any connector's *first-ever* run: the
  `ingestion_jobs` insert wasn't guaranteed to land after the `sources` insert, since no
  `relationship()` links those two models for SQLAlchemy's unit-of-work to infer order from a raw
  FK alone. Fixed with an explicit `db.flush()` between the two.
- `quality_gates.KNOWN_LICENSES` was missing license tags for each new connector
  (`public-archive-snapshot`, `CC0-1.0`, `odbl-opencorporates`), so their output was silently
  quarantined as `unknown_license` on first run.
- `get_connector()` was called with no config anywhere, so `crawler_user_agent` /
  `sec_edgar_user_agent` settings were dead — defined, documented, never reaching a connector
  instance. This also blocked `opencorporates_api_token` from ever reaching that connector.
- `wikidata`'s first sentence templates used passive voice (`"{subject} was founded by
  {value}."`), which the project's spaCy small-model NER reliably fails to tag as an ORG mention in
  short sentences — with no org mention in the sentence, relation extraction silently produced zero
  edges. Rewrote templates to active/copula voice, verified live against the actual model.

## [0.1.0] - 2026-07-09

Initial 7-plane platform build, in 8 phases (see git history for the full phase-by-phase detail
and every bug found and fixed during live verification):

- **Collection**: Wikipedia, SEC EDGAR, user upload, and a robots.txt-respecting web crawler behind
  one `Connector` interface with a plugin registry.
- **Ingestion & processing**: HTML/PDF/OCR extraction, language detection, PII tagging, quality
  gates, structural chunking.
- **Storage lakehouse**: Postgres (documents/chunks/entities/edges/governance) + MinIO/S3 bronze
  tier, Alembic migrations.
- **Retrieval substrate**: Postgres `tsvector` lexical + `pgvector` semantic search, fused with
  Reciprocal Rank Fusion, reranked with a local cross-encoder.
- **Knowledge & fusion**: spaCy NER, rule-based relation extraction, entity resolution (blocking →
  scoring → clustering → human review), Neo4j sync.
- **Query plane**: RAG pipeline (mock or live Claude synthesis) and a bounded agentic research mode,
  both citation-verified before returning.
- **Governance & security**: bearer-token auth, RBAC + ABAC, admin kill switch, DB-trigger-enforced
  immutable audit log, rate limiting.
- 42 unit tests, full README, live-verified end-to-end against real Postgres/Neo4j/MinIO.
