# Chiron ↔ Wardline: running side by side without duplicating infrastructure

*Written 2026-09-13, after integrating SpiderFoot into wardline and checking chiron's actual architecture (not just its README) to see what "side by side" really requires.*

*See [`MASTER_ROADMAP.md`](MASTER_ROADMAP.md) for how this track relates to the other two roadmap documents in this repo and what's actually being worked on next across all three.*

## Why this document exists

Wardline's README already treats [chiron](https://github.com/nixbys/chiron) as a sibling project whose tool *categories* are worth matching (`shodan`, `nmap`) without vendoring its AGPL-3.0 code — calling an independently-licensed service over a network boundary instead. Asked directly, the goal is for the two projects to run **side by side**: cooperating deployments, not one absorbing the other. That raises a question the shodan/nmap connectors never had to answer, because those call third-party APIs chiron has no copy of: **when both projects can reach the same capability, how do you avoid two independent, drifting copies of it?**

This document is the answer — a resource-overlap map to check before deploying both, and a phased plan for the deeper integration (chiron currently has no network-reachable API surface for wardline to call at all, which caps how far "side by side" can go without a change on chiron's own side).

## Already shipped (Phase 0 — this branch)

`connectors/spiderfoot.py`: an engagement-scoped `Connector` that calls a plain SpiderFoot REST API (start scan → poll → retrieve, one citable document per correlated finding). This doesn't depend on chiron's code — SpiderFoot itself is MIT and independently callable — but the *design* comes straight from chiron's own [ADR 003](https://github.com/nixbys/chiron/blob/main/docs/adr/003-spiderfoot-integration.md), which validated this exact architecture first (sidecar + REST + async lifecycle, not `exec`).

Critically, `SPIDERFOOT_URL` is a **plain external dependency** — the connector doesn't know or assume wardline owns the container it points at. That's what makes Phase 0 config-only: point wardline's `SPIDERFOOT_URL` at chiron's existing `odysseus-spiderfoot` instance instead of starting wardline's own `--profile spiderfoot` sidecar, and there is exactly one SpiderFoot in the deployment, not two burning the same Shodan/VirusTotal/OTX API quotas twice.

## Resource overlap map

Check every row before running both projects against the same targets/keys/host:

| Shared resource | The redundancy risk | What to do |
|---|---|---|
| **SpiderFoot** | Two containers, two scan histories, one shared third-party API quota (Shodan/VirusTotal/OTX) burned twice. | One instance. Whichever project's compose file starts it, the other points `SPIDERFOOT_URL` at it instead of starting its own (Phase 0, done). |
| **Active-scan toolchain** (nmap today; sqlmap/nuclei/masscan/gobuster/nikto/theHarvester if wardline's own README roadmap grows into them) | Wardline's `toolrunner` sidecar and chiron's `odysseus-toolchain` both execute nmap. Two containers capable of active network probing is two blast radii to reason about, not one — directly against `toolrunner`'s own "isolate the capability, limit blast radius" design goal. | **Needs Phase 2 below first** (chiron has no HTTP surface for this yet). Once it exists, wardline's `nmap` connector should target chiron's toolchain exec API instead of maintaining a second, narrower copy — don't build out wardline's own toolrunner into a bigger tool roster in the meantime; that's exactly the redundancy this section warns about. |
| **Authorization/engagement state** | Wardline's `Engagement` (`governance/engagements.py`) is a hard 403 gate with an evidence reference and a validity window; chiron's `engagement_server.py` is a softer case/timeline label with no enforcement. Running both independently means an analyst enters "the same" authorization twice, and worse, the two can drift — wardline could revoke access while chiron still considers a target in scope. | Designate one source of truth. Wardline's is the stricter primitive — recommend chiron defer to it (Phase 3) for anything reachable through the bridge, rather than keep two independently-decided answers to "is this authorized." |
| **Audit trail** | If both log "SpiderFoot scanned target X" as their own independent event, there are two competing records of one action — worse for compliance than either alone, since neither is unambiguously authoritative in a dispute. | Whichever system actually issued the authorization check and initiated the call is the audit-of-record (Phase 4); the other keeps a reference/pointer, not a duplicate full copy. Wardline's append-only, Postgres-trigger-enforced, PQC-signed export is the stronger candidate. |
| **Data stores** (wardline's Postgres/pgvector/Neo4j/MinIO vs. chiron's per-MCP-server SQLite files) | These model genuinely different things (a RAG/knowledge-graph substrate vs. case/finding/watchlist tracking). | Leave separate — not every overlap is worth deduplicating, and forcing a shared DB layer between two independently-evolving projects would trade a real coupling cost for no real benefit. |
| **Host ports** (if co-located on one machine) | Two compose stacks colliding on default ports. | Wardline's compose already parameterizes every host port (`*_HOST_PORT` env vars — see `scripts/provision_customer.sh`) for exactly this "more than one stack, one host" case; apply the same discipline to any of chiron's ports. |
| **LLM/API spend** | Not a technical redundancy, but a real dollar one: both systems independently call LLM providers and pay for it. | No dedup possible here (different products, different calls) — just worth visibility into combined spend if run together, not a design change. |

## Architecture gap: chiron has no network-reachable tool-execution API today

Chiron's MCP servers (`spiderfoot_server.py`, `osint_server.py`, `recon_server.py`, `engagement_server.py`, and 16 others) are all **stdio subprocesses** — spawned by chiron's own agent loop over `mcp.server.stdio`, not a persistent network service. `routes/toolchain_routes.py`'s `/api/toolchain/exec-modes` is the closest thing to an external HTTP surface today, and it's an admin status readout, not a tool-invocation endpoint. Concretely: **wardline cannot call chiron for anything beyond "point at the same third-party service's URL" (SpiderFoot, Phase 0) until chiron exposes something new.** This is a real, cross-repo change — chiron's own codebase and conventions, not something this session can build unilaterally into that repo without being asked to work there directly.

## Phased plan

**Phase 1 (this session, done): shared SpiderFoot.** Config-only, no bridge needed — see above.

**Phase 2: a minimal HTTP adapter on chiron's side for toolchain execution.** A small new service (mirroring wardline's own `toolrunner` sidecar: non-root, allowlisted routes, re-validates its own inputs rather than trusting the caller) wrapping chiron's existing `mcp_servers/common.py:exec_in_toolchain()` path. Scope it narrow on day one — nmap only, matching wardline's own `nmap` connector's current scope — rather than exposing chiron's full Kali toolchain roster at once.

**Phase 3: shared authorization.** Once Phase 2 exists, gate it on wardline's `Engagement`, not a second independent check: either chiron calls a new small read-only wardline endpoint (`GET /v1/admin/engagements/{id}` — already close to what `governance/engagements.py` stores) before running a gated tool, or wardline's own connector is the only caller of chiron's Phase 2 adapter (simpler: no new chiron-side auth-checking code at all, since the PEP check already happened in wardline before the call is made — the same trust relationship `nmap_scan.py` already has with `toolrunner`).

**Phase 4: shared audit-of-record.** Once Phase 2/3 exist, decide (don't default) which system's audit log is canonical for a bridged action, and have the other store a reference rather than a duplicate event.

**Phase 5 (stretch, evaluate before building): data interop.** Wardline's cited RAG answers as a source chiron's own `rag_server`/`intel_server` could consume, and/or chiron's findings/watchlist as a new wardline connector. Only worth doing if a real workflow needs it — not because the plumbing would be interesting to build.

## Decisions needed before Phase 2

1. **Who does the chiron-side work?** Phase 2 onward touches chiron's own repo/conventions, not wardline's — needs an explicit decision to work in that codebase (a different project with its own review process), not something to start from wardline's side alone.
2. **Deployment topology**: same host/network (simplifies auth — internal-only reachability, like `toolrunner` today) or separate hosts reachable over the internet (needs real TLS/auth on whatever Phase 2's adapter exposes, not just an internal-network assumption)? This changes Phase 2's design meaningfully, so settle it before scoping that phase further.
