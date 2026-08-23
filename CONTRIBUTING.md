# Contributing to wardline

## Dev environment

Requires Docker (or Podman with the `docker-compose` external provider). No host Python setup is
needed — dependency installation, spaCy model download, and test execution all happen inside the
`api`/`worker` images, since several dependencies (torch, sentence-transformers, spaCy) need a
matched Python version (3.12) that your host may not have.

```bash
cp .env.example .env             # edit API_KEY_PEPPER at minimum
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml run --rm api python -m alembic upgrade head
```

## Running tests

```bash
docker compose -f docker/docker-compose.yml run --rm api python -m pytest tests/unit -v
```

Unit tests are pure-logic (schemas, chunking, fusion math, entity-resolution scoring, RBAC/ABAC,
engagement scoping, citation verification) and don't require live Postgres/Neo4j/MinIO connections
— only the `docker compose run` plumbing does, since the `api` service's compose dependency graph
waits on those being healthy first.

There is no integration suite against real Postgres/Neo4j yet (see README's "Scope reductions"
table) — `testcontainers-python` is the noted next addition. Until then, the way to verify a
connector or pipeline change end-to-end is the same way this project was built: run it against the
live compose stack and inspect the database directly (see README's "How to use it").

## Linting

```bash
docker compose -f docker/docker-compose.yml run --rm api python -m ruff check src tests
```

CI runs the same check. Fix reported issues before opening a PR; don't suppress with blanket
`# noqa` unless the existing code's rationale (see inline comments near current `# noqa` uses)
genuinely applies.

## Adding a new connector

See README's "Adding a new source" section — implement `Connector`, register it, and if it's a
dual-use target-lookup tool (not a public-corpus source like Wikipedia/archive.org), set
`requires_engagement = True` and read `governance/engagements.py` first. Don't build a connector
that performs reconnaissance against arbitrary third-party targets without that scoping in place —
see README's "The legal boundary" section for why.

## Commit and PR conventions

- Commit messages: imperative mood, explain *why* not just *what* (the diff already shows what
  changed). If a commit fixes a bug found during manual/live verification, say what broke and how
  you confirmed the fix, the way existing commit messages in this repo do — `git log` is the actual
  record of what's been debugged and how.
- Keep PRs scoped to one concern. A connector addition and an unrelated governance change are two
  PRs, not one, unless the governance change exists specifically to support the new connector.
- Every new connector, governance primitive, or bug fix needs a corresponding unit test — this
  project's test suite is small specifically *because* it's tightly scoped to real bugs found and
  real contracts (schema fields, license allow-lists, scoring thresholds) that have already broken
  once. Don't let that coverage regress.
- CI (lint + unit tests + Docker build) must pass before merge.

## Reporting issues

There's no public issue tracker for this project yet. If you find a bug, include: what you ran,
what you expected, what happened instead, and (if applicable) the relevant `docker compose logs`
output — the same level of detail this repo's own commit messages use when documenting bugs found
during live testing.
