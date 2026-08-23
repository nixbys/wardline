# Security Policy

Wardline handles authentication, RBAC/ABAC, an immutable audit log, and
engagement-scoped dual-use connectors (Shodan lookups, active nmap scans) —
a real vulnerability here has real consequences. Please report privately, not
as a public issue.

## Reporting a vulnerability

**Preferred**: use GitHub's private
[Report a vulnerability](../../security/advisories/new) flow (Security tab →
Advisories → "Report a vulnerability") on this repo. It reaches maintainers
directly without creating a public issue, and lets us coordinate a fix and a
disclosure timeline with you through the same thread.

**Fallback**: email **security@wardline.example** (placeholder — replace
with a real, monitored address before this repo takes outside contributions
at any scale). Include:

- What you found and where (file/endpoint/connector).
- Steps to reproduce, or a proof-of-concept if you have one.
- What you think the impact is (e.g. "any `viewer`-role user can read
  `internal-only`-tagged documents", not just "found a bug").

Please don't open a public GitHub issue for a suspected vulnerability until
a fix has shipped and we've agreed on disclosure — see below.

## What's in scope

- Auth/session handling, API-key hashing, MFA (`governance/accounts.py`,
  `governance/mfa.py`).
- RBAC/ABAC enforcement (`governance/rbac.py`, `governance/abac.py`) —
  anything that lets a role see/do more than it should.
- Engagement scoping (`governance/engagements.py`, `governance/pep.py`) —
  anything that lets a dual-use connector (`shodan`, `nmap`) run without a
  valid, in-scope engagement, or scan outside the authorized target.
- The audit log's append-only guarantee (the Postgres trigger backing
  `audit_events`).
- Injection, SSRF, deserialization, or auth-bypass issues anywhere in
  `src/wardline/api/` or `src/wardline/connectors/`.
- Dependency vulnerabilities with a real exploitation path in how this
  project actually uses the dependency (not just "a CVE exists upstream" —
  see `CHANGELOG.md`'s Security section for how past ones were triaged).

## What's out of scope

- The `nmap` connector performing a TCP-connect scan against a target you
  yourself supplied an engagement for — that's the documented, intended
  behavior of authorized-pentest tooling, not a vulnerability. See
  [The legal boundary](README.md#the-legal-boundary).
- Findings that require an attacker to already hold `admin` credentials or
  host-level access to the deployment (out of this project's threat model —
  see [Production readiness](README.md#production-readiness) for the
  secrets/TLS/IAM posture that's the operator's responsibility).
- Missing rate limits on non-security-sensitive endpoints (tracked as a
  product gap in `docs/COMMERCIALIZATION_ROADMAP.md`, not a vulnerability).
- Anything in `.venv/`, generated caches, or other non-shipped local files.

## Supported versions

This project doesn't cut tagged releases yet (see `CHANGELOG.md`) — only the
tip of `master` is supported. Fixes land there; there's no backport policy
until versioned releases start.

## Disclosure timeline

We aim to acknowledge a report within 5 business days and to have a fix or a
mitigation plan within 90 days of confirming it, coordinating the public
disclosure date with the reporter. Credit is given in the fix's changelog
entry unless you'd rather stay anonymous.
