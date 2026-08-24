# Wardline

[![CI](https://github.com/nixbys/wardline/actions/workflows/ci.yml/badge.svg)](https://github.com/nixbys/wardline/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

A lawful OSINT + AI research platform: hybrid retrieval-augmented generation (lexical + vector + knowledge graph) over public, licensed, or consented sources, with governance, an immutable audit log, and an agentic research mode.

This is the buildable translation of a fictional "omniscient" information engine (the report this repo was built from used *Hliðskjálf* from *The Irregular at Magic High School* as its reference point) into real, lawful architecture. It answers natural-language questions with **cited, verifiable answers**, never asserting a claim it can't point to a source for.

*Renamed from "cranus" during a wider rebrand. One intentional fossil: the already-applied `migrations/versions/0001_initial_schema.py` still creates a Postgres function named `cranus_to_tsvector` — migration files describe exactly what was run against a real database, so that one isn't edited retroactively. It's an internal implementation detail (nothing public references the name), and any new migration is free to rename it later if that ever matters.*

## Table of contents

- [What this is not](#what-this-is-not)
- [Architecture](#architecture)
- [Setup](#setup)
- [How to use it](#how-to-use-it)
- [Adding a new source](#adding-a-new-source)
- [Authorized pentesting connectors](#authorized-pentesting-connectors)
- [Self-serve accounts](#self-serve-accounts)
- [Billing](#billing)
- [Governance](#governance)
- [Testing](#testing)
- [Production readiness](#production-readiness)
- [Scope reductions vs. the source report](#scope-reductions-vs-the-source-report)
- [The legal boundary](#the-legal-boundary)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## What this is not

This project deliberately does **not** implement mass interception of private communications, unauthorized access to systems, or anything resembling SIGINT/XKeyScore-style surveillance. Those are illegal almost everywhere (wiretapping/interception law, computer-misuse law, data-protection law) and are not "features left for later" — they are out of scope by design. Everything here operates over sources that are public, licensed for reuse, or provided by the user themselves (upload).

This also means a category of *dual-use* connectors (Shodan-style exposure search, active network reconnaissance) is treated differently from ordinary public-corpus sources: see [Authorized pentesting connectors](#authorized-pentesting-connectors) below. Every one of them requires an active, target-scoped `Engagement` before it can run at all — the governance primitive isn't just scaffolding anymore, two real connectors sit behind it.

## Architecture

Seven planes, matching the source report's design:

| Plane | Where it lives | What it does |
|---|---|---|
| Collection | `src/wardline/connectors/` | Wikipedia, Wikidata, SEC EDGAR, OpenCorporates, archive.org (Wayback Machine), user upload, and a robots.txt-respecting web crawler — all behind one `Connector` interface (`base.py`), discoverable via a plugin registry (`registry.py`) |
| Ingestion & processing | `src/wardline/ingestion/` | HTML/PDF/OCR extraction, language detection, PII tagging, quality gates (quarantine on failure), structural chunking |
| Storage lakehouse | `src/wardline/storage/` | Postgres (documents/chunks/entities/edges/governance), MinIO/S3 for bronze-tier raw bytes, Alembic migrations |
| Retrieval substrate | `src/wardline/retrieval/` | Postgres `tsvector` lexical search (or real OpenSearch BM25, `LEXICAL_BACKEND=opensearch`) + `pgvector` HNSW semantic search, fused with Reciprocal Rank Fusion, reranked with a local cross-encoder |
| Knowledge & fusion | `src/wardline/graph/` | spaCy NER, rule-based relation extraction, entity resolution (blocking → scoring → clustering → human review), Neo4j |
| Query plane | `src/wardline/query/`, `src/wardline/agent/` | The RAG pipeline (`query/pipeline.py`) and the bounded agentic research loop (`agent/loop.py`), both citation-verified before returning |
| Governance & security | `src/wardline/governance/` | Bearer-token auth, RBAC + ABAC, engagement-scoping for dual-use connectors, an admin kill switch, and an append-only audit log enforced by a Postgres trigger (not just application code) |

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

By default the query/agent planes run against `LLM_CLIENT_MODE=mock` — a deterministic, no-network synthesizer that does real extractive work over whatever retrieval actually finds (so the whole pipeline is exercisable without an API key). Set `LLM_CLIENT_MODE=live`, `LLM_PROVIDER`, and `LLM_API_KEY` in `.env` for genuine grounded synthesis from a real model.

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

# On-demand Iceberg export of the audit trail (also runs on iceberg_export_interval_seconds,
# default 6h — see "Scope reductions" below). Gives real time-travel/schema-evolution
# queries over the audit log via any Iceberg reader (PyIceberg, Spark, Trino, DuckDB).
curl -X POST http://localhost:8000/v1/admin/iceberg/export-audit-events -H "Authorization: Bearer $KEY"
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

### 6. Engagement scoping, then an authorized pentesting connector

Create the engagement first — this is the one admin action that asserts "this specific target lookup is authorized," so it needs a real reference to the authorization evidence (a signed SOW, a ticket), not just a role check:

```bash
curl -X POST http://localhost:8000/v1/admin/engagements \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"target": "example.com", "scope_note": "authorized external footprint assessment", "evidence_ref": "SOW-2026-001", "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2026-02-01T00:00:00Z"}'
```

The response's `id` is the `engagement_id` every dual-use connector run below requires. `target` can be a domain (subdomains are in-scope automatically) or a CIDR range like `"10.0.0.0/24"` (any IP inside it is in-scope) — see [Authorized pentesting connectors](#authorized-pentesting-connectors).

```bash
# shodan — exposure lookup, requires SHODAN_API_KEY in .env
curl -X POST http://localhost:8000/v1/admin/connectors/shodan/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"target": "203.0.113.7"}, "engagement_id": "eng_..."}'

# nmap — active scan, requires the toolrunner sidecar
# (docker compose -f docker/docker-compose.yml --profile toolrunner up -d toolrunner)
curl -X POST http://localhost:8000/v1/admin/connectors/nmap/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"params": {"target": "203.0.113.7", "ports": "22,80,443"}, "engagement_id": "eng_..."}'
```

Either call 403s immediately — before a job is even queued — if `engagement_id` is missing, revoked, expired, or doesn't cover the requested target.

## Adding a new source

Implement `Connector` (`src/wardline/connectors/base.py`: `discover()`, `fetch()`, `parse()`, `provenance()`), decorate the class with `@register_connector("your-name")`, and either add it to `connectors/registry.py`'s built-in import list, or ship it as a separate installable package that declares a `wardline.connectors` entry point — no change to this repo required for the latter. Add its `default_license` tag to `ingestion/quality_gates.KNOWN_LICENSES` or every document it ingests will be quarantined. It's then immediately usable via `POST /v1/admin/connectors/{name}/run`.

If your connector performs a target-lookup (not a fixed public corpus — think "look up everything about domain X" rather than "fetch Wikipedia page Y"), set `requires_engagement = True` (see next section) before wiring it in.

## Authorized pentesting connectors

RBAC answers "who are you." ABAC answers "what license does this document carry." Neither answers "who authorized looking at *this specific target* with a tool that's shaped like reconnaissance" — which matters for connectors like Shodan (internet-wide exposure search) or active network scanning. Those are legitimate for *authorized* security assessments (penetration tests, red-team engagements, your own infrastructure) and squarely out of scope for anything else — a general-purpose "look up anything about anyone" tool built on the same APIs is a different, riskier product than the encyclopedic/registry sources this project otherwise ingests.

`src/wardline/storage/models/engagements.py` + `governance/engagements.py` + `governance/pep.py:enforce_engagement_scope` implement the primitive: an `Engagement` records a target, a scope note, a reference to the authorization evidence (a signed SOW, a ticket), and a validity window. Any connector with `requires_engagement = True` cannot run without an active, non-expired, non-revoked engagement whose target covers the requested lookup (`POST /v1/admin/connectors/{name}/run` then requires `params.target` and `engagement_id`) — checked and rejected with a 403 *before* a job is even queued, not after. `target_in_scope` handles both domain suffixes ("acme.com" covers "www.acme.com") and real CIDR containment ("10.0.0.0/24" covers "10.0.0.5" but not "10.0.1.5"), since infrastructure engagements are routinely scoped to a network range rather than one host.

Two connectors sit behind this gate today, inspired by (but not built from — see the licensing note below) the tool categories in [Odysseus Red](https://github.com/nixbys/odysseus-red):

- **`shodan`** (`connectors/threat_intel.py`) — passive exposure lookup against Shodan's API. Needs `SHODAN_API_KEY`.
- **`nmap`** (`connectors/nmap_scan.py`) — active network scan. Runs in an isolated sidecar, never in the api/worker containers: `docker compose -f docker/docker-compose.yml --profile toolrunner up -d toolrunner` (see `docker/toolrunner/`), then set `TOOLRUNNER_URL`/`TOOLRUNNER_TOKEN`. The sidecar runs as a non-root user with no added capabilities — it only ever performs a TCP-connect-style scan, which doesn't need raw sockets.

Both are ingested through the normal pipeline (chunked, embedded, queryable, cited) but tagged `internal-only` (`governance/abac.py`), so results are visible to `admin`/`analyst` but not `viewer` — a materially different sensitivity class than public-corpus documents.

**Extending this to more of Odysseus Red's categories** (sqlmap, nuclei, masscan, gobuster, nikto, theHarvester, YARA, CVE/MITRE mapping) means repeating the exact same pattern: a new `Connector` subclass with `requires_engagement = True`, either a direct API call (like `shodan`) or a new allowlisted `/scan/<tool>` route on the toolrunner sidecar (like `nmap`) — never a generic "run any command" surface, and never vendoring another project's source into this repo (see below).

**Before enabling either connector for anything customer-facing, not just internal use:**
- **License boundary, on purpose**: this integration calls the same *kind* of open-source tools Odysseus Red bundles (nmap) and the same third-party APIs (Shodan) — it does not import, fork, or vendor Odysseus Red's own code, which is AGPL-3.0-or-later. Doing that would put this repository's combined work under AGPL too, including the network-service copyleft clause that would obligate offering source to every user of a hosted product built on it. Calling an independent, separately-licensed tool/service over a network boundary (the same pattern this project already uses for Postgres, Neo4j, and OpenSearch, all copyleft-licensed themselves) doesn't carry that obligation — keep it that way if you extend this further, and get real legal review before vendoring anything directly instead of calling it.
- **Tool-specific licenses**: nmap, sqlmap, and several of Odysseus Red's other tools carry their own (sometimes GPL-family, sometimes custom) licenses with their own redistribution terms, separate from the AGPL question above — review each one's license before bundling/redistributing it as part of a commercial product, not just before running it internally.
- **Third-party API Terms of Service**: Shodan's (and VirusTotal's/OTX's, if added later) ToS govern redistribution/resale of data their APIs return — review those before this connector's output feeds anything a paying customer sees.
- **This is active tooling, not just OSINT anymore**: `nmap` actively probes whatever target its engagement scopes — only ever point it at infrastructure you have explicit, documented authorization to test. See `docs/COMMERCIALIZATION_ROADMAP.md` for the compliance/insurance groundwork this implies before selling it as a product.

## Self-serve accounts

Two identity paths coexist, for two different kinds of caller: an admin still mints CLI/API keys directly (`create-admin-user`, `POST /v1/admin/users`) for scripts and service accounts, while a real person gets a password + optional MFA through `POST /v1/auth/*` (`src/wardline/governance/accounts.py`) — signing up, verifying email, logging in, resetting a forgotten password, and enabling TOTP two-factor with backup recovery codes. `web/login.html` is the UI for this; `web/app.html`'s "Sign in" prompt links to it.

Under the hood, a successful login just mints a normal `ApiKey` row tagged `scopes=["session"]` — everything else in this app (`get_current_user`, RBAC, the kill switch, the audit log) keeps working completely unchanged, because as far as they're concerned a browser session and a CLI key are the same kind of credential. Logging out or resetting a password only ever revokes *session*-scoped keys, never a long-lived key minted separately.

```bash
# Sign up, then check the API logs for the mock-mode "email" (EMAIL_MODE=smtp sends for real)
curl -X POST http://localhost:8000/v1/auth/signup \
  -H "Content-Type: application/json" -d '{"email": "you@example.com", "password": "a-long-enough-passphrase"}'

# Verify (token comes from the emailed/logged link)
curl -X POST http://localhost:8000/v1/auth/verify-email \
  -H "Content-Type: application/json" -d '{"token": "..."}'

# Log in — returns an api_key exactly like an admin-minted one
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" -d '{"email": "you@example.com", "password": "a-long-enough-passphrase"}'

# Enable MFA (authenticated) — TOTP secret, then confirm with a real code from an authenticator app
curl -X POST http://localhost:8000/v1/auth/mfa/enroll -H "Authorization: Bearer $KEY"
curl -X POST http://localhost:8000/v1/auth/mfa/confirm \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{"code": "123456"}'
```

An admin can invite a teammate instead of minting a key on their behalf — `POST /v1/admin/users/invite {"email": ..., "role": ...}` emails a link to `web/accept-invite.html`, where the recipient sets their own password.

Not yet built: passkeys/WebAuthn (TOTP is the first cut), org/workspace seat management, and the encrypted-conversation-vault privacy model — all tracked in `docs/COMMERCIALIZATION_ROADMAP.md`.

## Billing

Plans and their limits live in one place, `src/wardline/common/plans.py` — nothing else hard-codes a price or a cap. **The prices shipped there are placeholders**, not a business decision this repo makes for you; change `monthly_price_usd` whenever real numbers exist. `GET /v1/billing/plans` (public, no auth) is what a pricing page reads from, so the page and the enforcement can never drift apart.

`BILLING_MODE=mock` (the default) never calls Stripe: `POST /v1/billing/checkout` activates the plan immediately and locally, so the whole flow — including the webhook-shaped state transitions — is exercisable in dev/CI with no Stripe account. Set `BILLING_MODE=stripe` + `STRIPE_API_KEY`/`STRIPE_WEBHOOK_SECRET`/`STRIPE_PRICE_ID_{PRO,TEAM}` to go live: create a Product + Price per paid plan in the Stripe dashboard, paste the Price ids into `.env`, and point a Stripe webhook endpoint at `POST /v1/billing/webhook` for the `checkout.session.completed`/`customer.subscription.updated`/`customer.subscription.deleted` events `governance/billing.py` handles.

Enforcement sits in `governance/entitlements.py`, called from `POST /v1/query` before anything runs: a plan that doesn't include `research` mode gets a 403 for it, and `max_sources` is silently capped to the plan's ceiling rather than honoring whatever the caller asked for. `web/pricing.html` and `app.html`'s settings modal (current plan + "Manage billing", which opens Stripe's hosted customer portal) are the UI for this.

```bash
curl http://localhost:8000/v1/billing/plans   # public

curl -X POST http://localhost:8000/v1/billing/checkout \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{"plan_id": "pro"}'
```

Not yet built: per-plan rate limiting (today's `slowapi` limits are still flat, not plan-scoped — see `docs/COMMERCIALIZATION_ROADMAP.md`), and org-level (rather than per-user) subscriptions for the Team plan's actual seat management.

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
- **Enterprise IAM**: set `AUTH_MODE=oidc` (+ `OIDC_ISSUER`, `OIDC_JWKS_URL`, optionally `OIDC_AUDIENCE`/`OIDC_ROLE_CLAIM`) to validate bearer tokens against any real OIDC-compliant IdP (Okta, Auth0, Keycloak, Entra ID) instead of this project's own API-key system — see `api/oidc_auth.py`/`api/deps.py`. A user record is created/kept in sync locally on first sight (for revocation and audit-log foreign keys), with the IdP as the source of truth for role assignment. **Live-tested against a real Keycloak instance** (`tests/integration/test_oidc_live.py`, run by CI on every push — see "Scope reductions" below): a real signed token from a real IdP is validated end-to-end (signature/issuer/audience against the real JWKS endpoint), plus tampered-signature and wrong-issuer rejection. `docker compose --profile oidc up keycloak` stands up the same IdP locally. Okta/Auth0/Entra ID specifically remain untested (no free-tier account available here), but the code path exercised is identical across any OIDC-compliant IdP.
- **Dependency pinning**: `requirements-lock.txt` (generated via `pip freeze` inside the built image, see `scripts/regenerate_lockfile.sh`) pins every transitive dependency to an exact version. `pyproject.toml` keeps floating `>=` bounds for flexibility when adding new dependencies; the lockfile is what real deployments should actually install from for reproducible builds.
- **Backups**: `scripts/backup.sh`/`scripts/restore.sh` dump Postgres (`pg_dump`, online), Neo4j (`neo4j-admin dump`, brief downtime — Community Edition has no hot-backup path), and MinIO (`mc mirror`) into `backups/<timestamp>/`. **Not exercised against a full stop/restore cycle this session** — reviewed for correctness, not live-run, since doing so against this environment's real ingested data risked actual data loss if something in the exact `neo4j-admin` CLI flags for this image version were wrong. Test a full backup→restore cycle in a disposable environment before relying on it. You still need to copy the output off-host — a backup on the same disk isn't a backup.
- **Resource limits**: every `docker-compose.yml` service now sets `mem_limit`/`cpus` (api/worker: 2 GiB/2 CPU each, for the ML models loaded at runtime; neo4j: 2 GiB; postgres: 1 GiB; the rest smaller). These are starting points sized for a single small deployment — profile and adjust for your actual traffic/hardware.
- **Observability**: `/metrics` (Prometheus, via `prometheus-fastapi-instrumentator`) and OpenTelemetry tracing (via `opentelemetry-instrumentation-fastapi`) are both wired into the app now, not just declared as dependencies. Traces print to console by default; set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317` to route through the bundled `otel-collector` compose service, and edit `docker/otel-collector-config.yaml` to add a real backend exporter (Honeycomb, Grafana Cloud, Datadog, etc.) — it only logs to its own stdout by default.

## Scope reductions vs. the source report

The report this was built from sketches a larger platform than a single build session can responsibly implement in full. These substitutions are deliberate, not oversights:

| Report's ideal | This build | Why proportionate here |
|---|---|---|
| ~~Kafka streaming bus~~ **Implemented (optional)** | Postgres `SELECT ... FOR UPDATE SKIP LOCKED` job queue stays the zero-extra-infra default; `JOB_QUEUE_BACKEND=kafka` dispatches through a real Kafka topic instead (`worker/kafka_queue.py`), live-tested against a real single-node KRaft broker in CI | Closed as an opt-in upgrade path — a handful of slow-moving connectors still don't need a streaming bus running unconditionally; `docker compose --profile kafka up kafka` for local use |
| ~~Airflow/Prefect/Dagster~~ **Implemented (Prefect)** | The worker polling loop + `ingestion_jobs` table still dispatch jobs (see the job-dispatch row above), but each job now runs as a real Prefect flow (`ingestion/pipeline.py`): `run_connector_job` fans out one `ingest_item` **subflow** per discovered item, with the network/model/DB-touching steps as retrying tasks | Prefect chosen over Airflow/Dagster: no server to run for the default case (an ephemeral local API starts automatically); set `PREFECT_API_URL` to point at a real Prefect server/Cloud for production run history |
| ~~Iceberg/Delta over object storage~~ **Implemented (analytical export)** | Postgres stays the system of record for `documents`/`chunks`/`entities`/etc. — Iceberg tables aren't built for that access pattern — but `audit_events` (this app's own append-only table) now also exports into a real Iceberg table (`storage/iceberg_export.py`) with genuine time-travel and schema evolution | No new infra: the catalog reuses this app's own Postgres, the warehouse reuses whichever `blob_backend` is already configured. Scoped to the one dataset that's actually analytics-shaped (an immutable event log), not a wholesale storage-layer swap the OLTP tables don't need |
| ~~OpenSearch (true BM25)~~ **Implemented (optional)** | Postgres `tsvector`/`ts_rank_cd` stays the zero-extra-infra default; set `LEXICAL_BACKEND=opensearch` for a real OpenSearch BM25 index instead (`retrieval/opensearch_backend.py`), live-tested against a real OpenSearch in CI | Closed as an opt-in upgrade path rather than a default swap — a handful of documents still don't need a second search engine running unconditionally; `docker compose --profile opensearch up opensearch` for local use |
| ~~Full ASR pipeline~~ **Implemented** | Local, open-source transcription via `faster-whisper` (`ASR_MODEL`, default `tiny`) reachable through the `upload` connector — audio/video files get transcribed the same lawful, user-provided-data way PDFs/HTML/JSON already do | Closed as local/open-source rather than a cloud ASR API, matching this project's existing stance on embeddings/reranking; no new *scraping* connector against third-party audio/video platforms, since that would cross the same ToS/legal line "The legal boundary" below explains this project declines to cross |
| ~~Cloud/commercial OCR~~ **Implemented (untested against real AWS)** | Local Tesseract stays the default; `OCR_BACKEND=textract` switches to AWS Textract (`ingestion/extractors/textract_ocr.py`) | Code is real and unit-tested against a mocked boto3 client (real call shape validated via `moto`), but this repo has no AWS account to live-test the actual API against — run one real document through it by hand before relying on it |
| ~~Enterprise IAM live-IdP test~~ **Implemented** | Optional OIDC JWT auth mode (see Production readiness), now live-tested end-to-end against a real Keycloak in CI (`tests/integration/test_oidc_live.py`) rather than validated by code review alone | Closed for Keycloak specifically; Okta/Auth0/Entra ID remain untested for lack of a free-tier account, though the code path is IdP-agnostic. MFA/Vault/KMS remain the IdP's/secrets-manager's own responsibility, not this app's |
| ~~Splink/Dedupe entity resolution~~ **Implemented (batch)** | The incremental per-mention resolver (blocking/scoring/clustering) still runs at ingestion time — real-time EM training isn't a thing — but a periodic Splink batch pass (`graph/entity_resolution/splink_batch.py`, every `entity_resolution_batch_interval_seconds`, default 6h) now re-examines each entity type with a real DuckDB-backed Fellegi-Sunter comparison engine and merges/queues through the same governance thresholds | Closed for the complementary batch-reconciliation role Splink actually fits; see the module docstring for why match weights are set explicitly rather than EM-trained (small-sample instability) and how to switch to EM once a type has real volume |
| ~~Dependency-parse relation extraction~~ **Implemented** | spaCy dependency-tree walk (nsubj/nsubjpass/agent/dobj, `conj` coordination, relative-clause antecedents) from trigger tokens, not a keyword-only sentence match | Closed — see `graph/relation_extraction.py`; a narrowly-scoped single-candidate fallback covers the small model's occasional mis-parse of hyphenated "co-founded" without reintroducing the old cartesian-product false positives |

## The legal boundary

Building the *literal* fictional device this project translates from would mean mass interception of communications and unauthorized computer access — crimes in essentially every jurisdiction (wiretapping/interception statutes, computer-misuse law, data-protection law like GDPR). This is not a corner that was cut; it's the wall the design stops at. Everything in this repository operates over public, licensed, or user-provided data, with an audit trail, revocable access, a kill switch, and (for anything shaped like target reconnaissance) mandatory engagement scoping — the lawful capabilities are the whole point, and the boundary is enforced by refusing to build the rest, not by a configuration flag.

## Contributing

Contributions are welcome — connectors, governance primitives, bug fixes, docs. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for dev setup, test/lint commands, and PR conventions, and
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for the community standards this project holds
contributors to. Issue templates (bug report / feature request) and a PR template live under
[`.github/`](.github/) — use them; they front-load the context that makes a report or a review
fast instead of a back-and-forth. `CHANGELOG.md` tracks notable changes.

The short version:

1. Fork, branch, and stand up the dev stack per `CONTRIBUTING.md`'s "Dev environment" section
   (Docker-only, no host Python setup needed).
2. Keep PRs scoped to one concern, add tests for new behavior, and make sure lint + unit tests +
   the Docker build all pass — the same checks CI runs on every push.
3. If you're adding a connector, read [Adding a new source](#adding-a-new-source) first — dual-use,
   target-lookup connectors need engagement scoping, not just a role check.

## Security

Found a vulnerability? See [`SECURITY.md`](SECURITY.md) for what's in scope and how to report it
privately — please don't open a public issue for a suspected vulnerability.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE). This includes an explicit patent grant, which
matters given the security-tooling surface area ([Authorized pentesting
connectors](#authorized-pentesting-connectors)) this repo ships.
