# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project doesn't yet cut tagged
releases, so entries are grouped by work session instead of version number.

## [Unreleased]

### Changed
- Genericized LLM backend config: `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` → `LLM_API_KEY`/`LLM_MODEL`,
  plus a new `LLM_PROVIDER` setting (`query/llm_client.py`'s `get_llm_client()` now dispatches on
  it). Still calls the same Anthropic API by default — this only stops hard-coding the vendor name
  into public-facing settings/docs, and means adding a second provider later is a new branch, not
  a rename.
- Renamed the project from "cranus" to "Wardline" — package (`src/cranus` → `src/wardline`), CLI entry point,
  Docker images/compose service defaults, env var defaults, and every doc. `git log` and the one already-applied
  migration (`migrations/versions/0001_initial_schema.py`, which still creates a Postgres function named
  `cranus_to_tsvector` — deliberately not edited retroactively, see README) still carry the old name, on purpose.
  Chosen after an informal collision screen turned up active, unrelated companies already using several other
  candidates — not a substitute for a real trademark search before committing marketing spend.

### Added
- Billing (commercialization roadmap Phase 1 / Pillar 5): `common/plans.py` (Free/Pro/Team/Enterprise,
  placeholder prices — the one place a real number needs to change), `governance/billing.py` (Stripe
  Checkout + customer portal + webhook state machine, `BILLING_MODE=mock` activates a plan locally
  with zero Stripe calls, matching this project's mock/live convention), `governance/entitlements.py`
  (query-mode gating + `max_sources` cap by plan, enforced in `POST /v1/query` before anything runs),
  new `subscriptions` table (migration `0005_billing.py`), `api/routers/billing.py` (`/v1/billing/
  {plans, subscription, checkout, portal, webhook}`). New web pages: `pricing.html` (reads plan data
  live from the API, never a hard-coded copy) plus a billing section in `app.html`'s settings modal.
- Self-serve accounts (commercialization roadmap Phase 0 / Pillar 1): `POST /v1/auth/{signup,
  verify-email, login, logout, password/forgot, password/reset, mfa/enroll, mfa/confirm,
  mfa/disable, accept-invite}` + `GET /v1/auth/me` (`governance/accounts.py`, `governance/mfa.py`,
  `api/routers/auth.py`), plus `POST /v1/admin/users/invite` for admin-issued teammate invites.
  TOTP MFA with recovery-code backup (`pyotp`). A successful login mints a normal `ApiKey` row
  tagged `scopes=["session"]` rather than a parallel session system — `get_current_user`, RBAC,
  the kill switch, and the audit log all keep working unchanged. New `password_hash`,
  `email_verified_at`, `mfa_secret`, `mfa_enabled` columns on `users`, plus `auth_tokens` and
  `recovery_codes` tables (migration `0004_accounts.py`). Outbound email via `common/email.py`
  (`EMAIL_MODE=mock` logs instead of sending, matching this project's `LLM_CLIENT_MODE=mock`
  convention; `EMAIL_MODE=smtp` sends for real against any standard provider). New web pages:
  `login.html`, `verify-email.html`, `reset-password.html`, `accept-invite.html`, plus an MFA
  management panel in `app.html`'s settings modal.
- Two engagement-scoped dual-use connectors — `shodan` (`connectors/threat_intel.py`, passive
  exposure lookup) and `nmap` (`connectors/nmap_scan.py`, active scan, run in a new isolated
  `toolrunner` sidecar container — `docker/toolrunner/`, optional `--profile toolrunner`) — the
  first connectors to actually use `requires_engagement`/`enforce_engagement_scope`, previously
  scaffolding with nothing behind it. Both tagged `internal-only` (ABAC), inspired by (not
  vendored from — kept at arm's length specifically to avoid AGPL scope creep) Odysseus Red's
  tool categories. `governance.engagements.target_in_scope` now understands CIDR ranges, not just
  domain suffixes, since infra engagements are routinely scoped to a network block.
- `docs/COMMERCIALIZATION_ROADMAP.md`: production/accounts/encryption/go-to-market plan, written
  against this repo's actual state rather than a generic SaaS checklist.
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

- `ingestion/extractors/audio.py`: local speech-to-text via `faster-whisper` (`ASR_MODEL`, default
  `tiny`), reachable through the existing `upload` connector -- audio/video files get transcribed the
  same lawful, user-provided-data way PDFs/HTML/JSON already do, not a new scraping-style connector
  against a third-party platform. Local/open-source rather than a cloud ASR API, matching this
  project's existing embeddings/reranking stance. `tests/unit/test_audio.py` runs the real "tiny"
  model end-to-end against a synthetic WAV (a decode/transcribe pipeline smoke test, not an accuracy
  test -- the input is a pure tone, not speech).

- `worker/kafka_queue.py`: an optional real Kafka job-dispatch backend (`JOB_QUEUE_BACKEND=kafka`),
  the noted upgrade path from the Postgres `SELECT ... FOR UPDATE SKIP LOCKED` queue. Postgres stays
  the zero-extra-infra default. The `IngestionJob` row is still created either way (it's this app's
  audit trail / job-status API, not just a work queue); Kafka is purely the dispatch signal, with
  `worker/jobs.py::claim_job_by_id` still doing the state transition as a second guard against ever
  double-running one job on redelivery. `docker compose --profile kafka up kafka` for local use
  (KRaft mode, no ZooKeeper); CI runs a real single-node broker and
  `tests/integration/test_kafka_queue.py` against it. Tracked down a well-known but easy-to-miss
  single-node gotcha along the way: Kafka's default `offsets.topic.replication.factor=3` can never be
  satisfied by one broker, so every consumer-group operation fails with `COORDINATOR_NOT_AVAILABLE`
  *silently* (no error surfaced, requests just never complete) until it's set to `1`.

- `ingestion/pipeline.py` orchestrated as a real Prefect flow (the noted Airflow/Prefect/Dagster
  upgrade path): `run_connector_job` is the parent flow, `ingest_item` runs as a subflow per
  discovered item (a genuine fan-out shape, addressing the scope-reduction row's own "not a fan-out
  DAG" justification), and the network/model/DB-touching steps (fetch, persist, index+graph-process)
  are tasks with automatic retries and backoff. Prefect chosen over Airflow/Dagster specifically
  because it needs no server for the default case -- an ephemeral local API starts automatically;
  set `PREFECT_API_URL` for a real server/Cloud. `tests/integration/test_ingestion_pipeline_prefect.py`
  runs the real flow end-to-end against a real Postgres (using `prefect_test_harness` for isolation),
  covering both the ingest and duplicate-detection paths. Verified locally against real
  Postgres/Neo4j/local-blob-storage before pushing -- also surfaced that the local dev `.env`'s
  `BLOB_BACKEND=s3`/MinIO default hangs badly (DNS+retry backoff) rather than failing fast when MinIO
  isn't running, unrelated to this change but worth knowing.

- `storage/iceberg_export.py`: a real Iceberg table (genuine time-travel and schema evolution) mirroring
  `audit_events` -- this app's own append-only table, exactly the analytics-shaped dataset the noted
  Iceberg/Delta upgrade path is for, not a wholesale swap of the OLTP tables (`documents`/`chunks`/
  `entities`) that don't need it. No new infrastructure: the catalog reuses this app's own Postgres
  (pyiceberg's `SqlCatalog`), the warehouse reuses whichever `blob_backend` is already configured
  (local filesystem by default, the same MinIO/S3 bucket when `BLOB_BACKEND=s3`). Idempotent/
  incremental (tracks the latest exported `created_at` via a scan of the Iceberg table itself). New
  admin endpoint `POST /v1/admin/iceberg/export-audit-events`, also runs on a schedule
  (`iceberg_export_interval_seconds`, default 6h). `tests/integration/test_iceberg_export.py` verifies
  real incremental export and real time-travel (an old snapshot still reports the old row count after
  the table has since grown) against a real Postgres. Verified locally end-to-end (including that
  `audit_events`' append-only DB trigger genuinely rejects DELETE, confirmed by a test fixture that
  originally tried to clean up that way) before pushing.

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
- **Query plane**: RAG pipeline (mock or live LLM synthesis) and a bounded agentic research mode,
  both citation-verified before returning.
- **Governance & security**: bearer-token auth, RBAC + ABAC, admin kill switch, DB-trigger-enforced
  immutable audit log, rate limiting.
- 42 unit tests, full README, live-verified end-to-end against real Postgres/Neo4j/MinIO.
