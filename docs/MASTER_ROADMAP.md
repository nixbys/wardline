# Wardline: master roadmap

*Written 2026-09-13. One index over the three roadmap documents this repo now carries, since they were written independently (at different times, for different asks) and nothing tied them together or said which phase to actually work on next. This doc doesn't repeat their content — it cross-references, states current status per track, resolves the one real cross-track conflict, and lists exactly what's safe to execute without a further decision versus what's still waiting on one.*

## The three tracks

| Track | Doc | What it's for |
|---|---|---|
| **Commercialization** | [`COMMERCIALIZATION_ROADMAP.md`](COMMERCIALIZATION_ROADMAP.md) (+ [`DEPLOYMENT_PQC.md`](DEPLOYMENT_PQC.md) for Pillar 3.1) | Turning wardline from an internal tool into a sellable product: accounts, billing, privacy/PQC, compliance, packaging. |
| **Live Globe** | [`LIVE_GLOBE_FULL_INTEGRATION_ROADMAP.md`](LIVE_GLOBE_FULL_INTEGRATION_ROADMAP.md) | A public, no-login 3D geospatial view (`globe/`), and the fuller integration of the project it's inspired by (bilawalsidhu/gods-eye-view) via a real fork. |
| **Chiron bridge** | [`CHIRON_WARDLINE_BRIDGE_ROADMAP.md`](CHIRON_WARDLINE_BRIDGE_ROADMAP.md) | Running wardline side by side with the sibling AGPL-3.0 project [chiron](https://github.com/nixbys/chiron) without duplicating infrastructure. |

These are genuinely independent — no track's code depends on another's — so they can proceed in parallel. The one place they touch is `docker-compose.yml` (each track adds its own optional profile-gated service: `toolrunner`/`spiderfoot` today, a possible future `globe-server`) and the README's growing "Authorized pentesting connectors" / feature-section list — both additive, no conflict, just something to keep tidy as all three grow.

## Status at a glance

**Commercialization** — Phases 0-2 essentially done (see that doc's own "Status update" section for the full checklist: accounts, billing plumbing, org/seats, encrypted vault, PQC audit-export signing all shipped). What's left is almost entirely **outside this repo's own reach**: legal entity formation, a live (non-mock) Stripe verification, a pen test, SOC 2. The one still-open, purely-engineering item is the **Ops Console** (`web/ops.html` + graph/jobs/audit/terminal admin tooling) — mentioned in that doc as "tracked separately... see the active plan file," but no such plan file actually exists in this repo (checked directly — it was likely an ephemeral planning artifact from an earlier session that was never committed). Treat that reference as stale; this doc is now the place it's tracked.

**Live Globe** — Phase 0 shipped (backend proxy, two citable-event connectors, the wardline-themed frontend). Phase 1 (fork + theming spike) is scoped and the fork exists ([nixbys/gods-eye-view](https://github.com/nixbys/gods-eye-view)) but had no commits yet as of that doc's last update, pending a pacing decision.

**Chiron bridge** — Phase 1 shipped (`connectors/spiderfoot.py`, config-only shared-instance story). Phase 2 onward needs a change to chiron's own codebase — a different repository with its own conventions and review process — which this session cannot start without that repo being made available to work in directly.

## Resolving the one real conflict: what to actually work on next

Every "next phase" across all three docs was deliberately written with its own gate — a pacing question, an explicit go-ahead requirement, or a dependency on a decision only the user can make. Lumping them into one master list makes it possible to see, for the first time, which of those gates are genuinely blocking versus which were just "ask before spending more effort," so this session's next work is chosen correctly instead of either stalling on every gate or barreling through all of them uniformly.

| Phase | Track | Gate type | This session |
|---|---|---|---|
| Ops Console | Commercialization | None — pure engineering, no external decision, wardline-only | **Ready. Needs a scoping pass first** (the one-sentence mention in the commercialization doc isn't a real spec) — see below. |
| Live Globe Phase 1 (fork theming spike) | Live Globe | Was "ask before starting" — a pacing preference, not a real blocker; small, reversible, already fully specced | **Ready — starting this now** as part of executing "the phases," per this session's instruction. |
| Live Globe Phase 2+ (sidecar, per-source rollout) | Live Globe | Depends on Phase 1 landing first | Not started. |
| Chiron bridge Phase 2 (HTTP adapter on chiron's side) | Chiron bridge | **Real blocker**: (1) touches a different repository not available to this session to work in directly, (2) chiron is a pentesting toolkit — a new tool-execution HTTP surface is a security-relevant design change that genuinely warrants your review before code exists, not just before it ships | **Not starting.** Needs chiron made available as a working repo, plus a decision on deployment topology (same-host vs. internet-reachable — changes the design). |
| Commercialization Phase 3-4 items (legal entity, live Stripe, pen test, SOC 2) | Commercialization | Real-world actions outside a repo's reach | Not started — nothing to code here. |
| Path A vs. Path B (multi-tenancy) | Commercialization | Business decision | Still open, unchanged from that doc. |

## What's happening in this session, concretely

1. **Live Globe Phase 1**: fork the theming spike into `nixbys/gods-eye-view` — a `wardline-theme.css` override on top of `foundation.css`'s existing custom-property scheme, verified by a real `npm run build`/`dev`, committed and pushed to the fork. Small, additive, reversible.
2. **Ops Console**: needs a real scoping pass before code — "graph/jobs/audit/terminal admin tooling" names four different surfaces without saying what any of them actually show or how they're gated. This gets its own plan before implementation starts, not a guess dressed up as a spec.

## Decisions still open (consolidated from all three docs)

- **Path A vs. Path B**, and hosted/self-host/both — commercialization's multi-tenancy question, unchanged.
- **Target buyer / first compliance cert** — commercialization go-to-market, unchanged.
- **Chiron bridge Phase 2**: who does the chiron-side work, and same-host vs. internet-reachable topology — needs chiron available as a working repo before this can even be scoped further, let alone built.
- **Live Globe pace beyond Phase 1**: how far to take the fork-based full integration (Phases 2-5) versus staying with Phase 0's lean build indefinitely.

Nothing above blocks the two concrete items in progress this session — they're called out because "start working on the phases" shouldn't be read as license to also start the ones this doc just finished explaining are genuinely gated on someone else's decision.
