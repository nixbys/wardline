---
name: wardline-review
description: Context-aware review checklist for the wardline repo -- branch/PR discipline, the mock/live external-integration convention, RBAC/plan gating, migration-chain hygiene, the untracked-roadmap-doc scrub rule, and the Path A/B multi-tenancy boundary. Use when reviewing a diff, branch, or PR in this repo, not generic-purpose code review.
---

# Wardline code review

This repo has house conventions a generic review misses. Read the diff, check it against every item below that applies, and report findings with the ReportFindings tool (most severe first; call it once even with zero findings). Skip items with nothing in the diff to check -- this is a checklist to apply, not a report to pad.

## Process conventions

- **Branch + PR, never a direct push to `master`** -- even though admin bypass works, every change here goes through a feature branch and PR. A diff or commit log showing `master` as the working branch is a finding.
- **No AI attribution** in commit messages or PR descriptions/comments -- flag any "Generated with Claude" / co-author trailer that slipped through (a repo hook blocks these in Bash, but a diff-only review can still catch one authored another way).
- **Untracked roadmap docs stay untracked and unnamed**: `docs/MASTER_ROADMAP.md`, `COMMERCIALIZATION_ROADMAP.md`, `LIVE_GLOBE_FULL_INTEGRATION_ROADMAP.md`, `CHIRON_WARDLINE_BRIDGE_ROADMAP.md`, `ECOSYSTEM_USAGE_ANALYSIS.md`, `ADAPTIVE_INTELLIGENCE_ROADMAP.md` are gitignored internal planning notes. Any tracked file (code comment, docstring, README, script) that names one of these files directly is a finding -- it should read "per internal planning notes" / "tracked internally" instead. Check `git ls-files` before trusting a path looks tracked.
- **Migration chain hygiene**: a new table/column needs a numbered `migrations/versions/NNNN_*.py` whose `down_revision` points at the actual current head, not a stale one guessed from memory. `alembic heads` (or `ScriptDirectory.get_heads()`) must resolve to exactly one revision after the change.

## Architectural conventions

- **Mock/live pairing for every external integration**: `LLM_CLIENT_MODE`, `EMAIL_MODE`, `BILLING_MODE` all follow the same shape -- a `mock` default that fully exercises the code path with no real credentials or network call, and a real mode gated behind explicit settings. A new external dependency (a new API key, a new paid service) that skips this pairing -- i.e. that can't be exercised in CI without a real account -- is a finding.
- **RBAC on every admin/analyst route**: new endpoints under `/v1/admin/*` must depend on `require_role(...)` (see `api/deps.py`), matching `admin_graph.py`/`admin_connectors.py`'s `_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)` pattern. A new admin route with no role dependency, or gated only by client-side UI, is a finding. A new **public** route should be deliberate (stated in its own docstring why) and rate-limited via `governance.rate_limit.limiter`, matching `donate`/`enterprise-inquiry`'s reasoning.
- **Plan/entitlement integrity**: `governance/entitlements.py` is the only enforcement point for `common/plans.py`'s caps, called from `POST /v1/query` before anything runs. A change that lets a request bypass `enforce_mode_allowed`/`capped_max_sources`, or that silently raises a plan's effective limits without updating `plans.py` itself, is a finding. `Donation` and `EnterpriseLead` rows must never grant a `Subscription`/plan implicitly -- flag any code path that reads either to affect entitlements.
- **Path A vs. Path B multi-tenancy is a standing open business decision** -- Enterprise means a dedicated per-customer instance (`scripts/provision_customer.sh`), not shared infrastructure. A diff that adds `org_id`-style row-level tenant scoping to core knowledge-base tables (`Document`, `Chunk`, `Entity`, anything `graph/repository.py` touches) is scope creep into that undecided territory -- flag it as a business-scope question for the user, not a routine schema change, even if the code itself is correct.
- **Ops Console parity**: a new admin-facing capability (list/search/toggle/create) that has no corresponding `web/ops.html` panel + `api.js` method is likely an oversight, not a deliberate omission -- flag it unless the PR description says the UI is deferred on purpose.

## Verification

- This sandbox's native `.venv` is unreliable (wrong Python version/deps from an earlier project name). Don't trust "should pass" reasoning about tests/lint -- verify via the project's own podman workflow: `podman build -f docker/Dockerfile.api -t wardline-api-test .`, then `podman run --rm -v "$(pwd):/app:Z" -w /app --entrypoint pytest wardline-api-test tests/unit -q` and `--entrypoint ruff wardline-api-test check src tests` (set `-e RUFF_CACHE_DIR=/tmp/ruff_cache` -- the bind mount's ownership blocks ruff's own cache dir otherwise).
- `ruff`'s selected rule set (`pyproject.toml`'s `[tool.ruff.lint]`) does not include `E501` (line length) -- a long line is not a lint finding in this repo; don't flag it as one.

## Output

Report findings with the ReportFindings tool per its own schema (file, line, summary, failure_scenario, category, short_summary, most severe first). If nothing above applies to the diff, call it with an empty findings list rather than skipping the call.
