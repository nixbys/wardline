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
- CI's lint job floated to whatever `ruff` was latest on each run; 0.16.x enables far more
  default-adjacent rule families than this repo was last green against, so 76 pre-existing findings
  surfaced with no code change of ours. Pinned `ruff==0.16.3` in both `pyproject.toml` and
  `ci.yml`, added an explicit `[tool.ruff.lint]` select list, and fixed the real findings
  (`datetime.now(UTC)` throughout, explicit `zip(..., strict=True)`, a dict-literal instead of
  `dict()`, a redundant `.replace("Z", ...)`, a collapsible nested `if`, and passing the exception
  object explicitly to `exc_info=` in the global FastAPI exception handler since it runs as an ASGI
  callback, not inside a literal `except:` block).
- `graph/relation_extraction.py` linked *every* Person mention to *every* Organization mention in
  any sentence containing a trigger word ("founded", "acquired", ...), regardless of which noun
  phrase the verb actually attached to — a bystander or an unrelated org named in the same sentence
  produced a spurious edge. Replaced the sentence-scoped keyword match with a dependency-tree walk
  from the trigger token (nsubj/nsubjpass/agent/dobj, `conj` coordination, relative-clause
  antecedent resolution), with a narrowly-scoped single-candidate fallback for the small model's
  occasional mis-parse of a hyphenated "co-founded". See the updated scope-reductions table.

- `graph/entity_resolution/splink_batch.py`: a periodic Splink batch dedupe pass complementing the
  incremental per-mention resolver — real DuckDB-backed Fellegi-Sunter comparison instead of a
  fixed weighted average, re-examining each entity type on a schedule
  (`entity_resolution_batch_interval_seconds`, default 6h) and catching duplicates the fast
  incremental path's blocking missed. Decisions flow through the existing merge/review governance
  (`review.merge_entities`, now public; `review.queue_for_review`). New admin endpoint
  `POST /v1/admin/entity-review/batch-resolve`. New `tests/integration/` suite (first entry in that
  previously-empty directory) exercising the full pass against a real Postgres, now also run by CI.

- Live-tested `AUTH_MODE=oidc` against a real Keycloak instead of code review alone: CI now starts a real
  `quay.io/keycloak/keycloak` container (a `docker run` step, not a `services:` block -- the official image
  needs a `start-dev` command argument that block has no way to pass) and
  `tests/integration/test_oidc_live.py` provisions a throwaway realm/client/role via the admin REST API,
  gets a real signed token, and validates it end-to-end through `oidc_auth.validate_token` -- plus
  tampered-signature and wrong-issuer rejection. Found and fixed a real bug this surfaced: the default
  `OIDC_ROLE_CLAIM=roles` assumed a flat top-level claim, but Keycloak puts realm roles at nested
  `realm_access.roles` -- `oidc_auth._resolve_role` now resolves a dotted claim path, and the default
  changed to match Keycloak's actual shape. `docker compose --profile oidc up keycloak` stands up the
  same IdP locally (not started by default).

- `retrieval/opensearch_backend.py`: an optional real OpenSearch BM25 lexical backend
  (`LEXICAL_BACKEND=opensearch`), the noted upgrade path from Postgres `tsvector`/`ts_rank_cd`'s
  BM25-*like* ranking. Postgres stays the zero-extra-infra default -- this is an opt-in swap, not a
  replacement, matching the project's own stated rationale for not requiring a second search engine
  unconditionally. `retrieval/index.py` dual-writes to OpenSearch when enabled;
  `retrieval/lexical.py`'s public `lexical_search()` dispatches to it transparently, so fusion/
  rerank/API code needs no changes either way. `docker compose --profile opensearch up opensearch`
  for local use; CI runs `tests/integration/test_opensearch_backend.py` against a real OpenSearch
  service container.

- `ingestion/extractors/textract_ocr.py`: an optional AWS Textract OCR backend (`OCR_BACKEND=textract`)
  for scanned PDF pages, the noted upgrade path from local Tesseract for messier scans/handwriting.
  Local Tesseract stays the default (no external account needed). No AWS account is available in
  this environment to live-test the actual API, so this is unit-tested against a mocked boto3 client
  instead: `moto` validates the real botocore call shape is accepted, and a hand-built response
  validates the LINE-block text-joining logic moto's stub can't exercise. Documented in the README
  as untested-against-real-AWS, not hidden.

### Security
- Bumped `pypdf` 6.14.2 → 6.16.0, closing Dependabot alerts #3/#4 (GHSA-fwg2-594c-jp42,
  GHSA-fp3f-mc75-235c: memory/runtime DoS on crafted `/ToUnicode` and CID-width PDF streams).
- Bumped `cryptography` 49.0.0 → 50.0.0 (Dependabot #2: PKCS#7 `EnvelopedData` Bleichenbacher
  oracle via distinguishable errors/timing).
- Dismissed Dependabot #1 (`ecdsa`, Minerva timing attack, no upstream fix — the project's stated
  position is that side-channel resistance is out of scope for pure Python). Verified this app's
  actual dependency resolution: `python-jose[cryptography]`'s backend selector always picks
  `CryptographyECKey` when `cryptography` is importable (it always is here), so
  `jose.backends.ecdsa_backend`'s vulnerable pure-Python path is never imported for JWT
  verification.

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
