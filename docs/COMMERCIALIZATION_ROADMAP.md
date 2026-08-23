# From internal tool to product: Wardline's roadmap toward a Lumo-style commercial launch

*Written 2026-08-22. Grounded in the actual state of this repository, not a generic SaaS checklist — every "already have" claim below points at real code, and every "gap" claim was checked against it first.*

## Read this part first: the "quantum encryption" question

You asked for quantum encryption specifically, the way Proton's Lumo does it. I want to correct the premise before planning around it, because building toward the wrong target wastes the money this plan is trying to make.

**Proton doesn't run quantum encryption either — and neither does anyone else, for a product like this.** "Quantum encryption" properly refers to Quantum Key Distribution (QKD): physically exchanging key material encoded in single photons over dedicated fiber, between two fixed points, with specialized hardware at both ends. It doesn't run over the ordinary internet, it doesn't work for a browser talking to a multi-tenant cloud API, and no consumer or B2B SaaS product — Proton included — uses it. If a plan promises this, it's promising something that can't be delivered on this kind of product.

**What Proton actually does, and what's real to aim for, is two separate things:**

1. **Zero-access encryption** — data encrypted with a key derived from the user's own credentials, such that even Proton's own servers/staff can't read it. This is genuinely implementable and is the part of "Lumo" worth copying.
2. **Post-quantum cryptography (PQC)** — ordinary math-based encryption (not quantum physics), but using algorithms believed to resist attack even by a future large-scale quantum computer (NIST-standardized **ML-KEM** for key exchange, **ML-DSA**/**SLH-DSA** for signatures). Proton has published real work adding hybrid classical+PQC key exchange to Proton VPN and their OpenPGP stack, specifically to defend against **"harvest now, decrypt later"** — an adversary recording today's encrypted traffic to break open once quantum computers are capable enough.

Everywhere the rest of this document says "PQC" or "post-quantum," that's the accurate, buildable version of what you asked for. I'll flag it again at the point in the plan where it actually gets implemented, so it isn't lost in translation.

---

## Where Wardline already stands (don't rebuild this)

This was scoped and built as a **single-organization internal research tool**, not a multi-tenant SaaS — that's the one sentence that explains most of what's missing below. But within that scope, more production groundwork already exists than the "add accounts and encryption" framing suggests:

| Capability | Already real, in-repo |
|---|---|
| TLS | `caddy` service auto-provisions Let's Encrypt certs from `DOMAIN`; terminates 8080/8443 |
| Enterprise SSO | `AUTH_MODE=oidc` validates bearer tokens against any OIDC IdP (Okta/Auth0/Keycloak/Entra ID), live-tested against real Keycloak in CI |
| Secrets | `/run/secrets` file-mount support wins over env vars — drop in a Vault-agent-rendered file or a Docker/K8s secret |
| Credential hashing | API keys already argon2id-hashed with a server-side pepper (`common/security.py`) — the exact primitive to reuse for user passwords |
| RBAC + ABAC | `admin` / `analyst` / `viewer` roles, engagement-scoping for dual-use connectors |
| Audit log | Append-only, enforced by a Postgres `BEFORE UPDATE OR DELETE` trigger that even the table owner can't bypass — not just an application-level convention |
| Admin kill switch | Global emergency stop, already wired through `get_current_user_active` |
| Rate limiting | `slowapi`, per-route, configurable |
| Observability | Prometheus `/metrics` + OpenTelemetry tracing wired into the app, not just declared as a dependency |
| Backups | `scripts/backup.sh`/`restore.sh` for Postgres/Neo4j/MinIO |
| Dependency pinning | Full transitive lockfile, regenerated from the built image |
| Scale-out options | Optional Kafka job dispatch, optional Prefect orchestration, optional OpenSearch BM25, optional AWS Textract OCR — all real, all opt-in via env var |

None of this needs redoing. The gap is specific and structural, not "the app isn't production-grade."

## The actual gap

I checked the schema and auth code directly. Three things are true simultaneously:

1. **`User` has no password.** It's `id / email / role / revoked` — identity comes from an admin-minted API key or an external IdP. There is no self-serve signup, no email verification, no password, no MFA, no account-recovery flow. A public product needs all of that.
2. **There is no tenant concept anywhere in the schema.** `grep -rn "tenant" src/` returns nothing. Documents, chunks, entities, graph edges, the audit log — all of it is global to one deployment. `GET /v1/audit` is explicitly documented as "the shared, browsable query log **every** authorized user can read" (report §4.6, "everyone sees every search") — a great feature for one org's internal transparency, and a data breach if two paying customers ever share a deployment.
3. **There's no billing, no plan/entitlement model, and (until this session) no account-facing web UI at all** — only a JSON API meant to be called with a key someone already has.

Item 2 is the one that actually decides your timeline and cost, so the next section makes it a decision rather than an assumption.

## The fork in the road: two legitimate paths, pick one before writing code

### Path A — Dedicated instances, sold like a product (fast)

Every customer gets their own deployment (their own `docker compose up`, their own Postgres/Neo4j/MinIO, either on your infrastructure or theirs). No new data-isolation code is needed — **isolation is physical, not logical**, because nothing is shared. You sell:
- a **hosted** tier (you run their stack, they never touch a terminal — this is "SaaS" from the buyer's perspective, and it's what most of this section still applies to: accounts, billing, PQC-in-transit, compliance)
- a **self-hosted** tier (they run it — genuinely stronger privacy than anything Lumo can offer, since their data never leaves their network; this becomes your sharpest positioning against Lumo/Perplexity, see Go-to-Market below)

This is buildable on **today's schema, unchanged**. Accounts, billing, and orchestration are the only new work. It's the path that gets you charging money soonest.

### Path B — True multi-tenant SaaS (slower, cheaper per-customer at scale)

One deployment serves every customer, isolated logically: `tenant_id` added to every table (`documents`, `chunks`, `entities`, `edges`, `audit_events`, `sessions`, `feedback`, connector configs, jobs), enforced with Postgres **Row-Level Security** so a bug in application code can't leak across tenants even if it tries. The graph store is the hard part: **Neo4j Community Edition supports exactly one database** — real tenant isolation there means either upgrading to Neo4j Enterprise (multi-database), encoding `tenant_id` as a property on every node/edge and disciplining *every single Cypher query* to filter on it (fragile — one missed `WHERE` leaks data), or giving larger customers their own Neo4j instance while small ones share. None of these are free.

**Recommendation: start on Path A.** It's a real product sooner, it's compatible with everything already built, and it doesn't force the Neo4j multi-tenancy decision before you have paying customers to fund it. Treat Path B as a Phase 3+ migration once (if) usage justifies the shared-infrastructure economics — the account/billing/PQC work below is designed to survive that migration either way.

---

## Pillar 1 — Accounts, the way a public product needs them

- **Signup**: email + password (argon2id via the existing `PasswordHasher` — same library, new field on `User`), email verification token, or "continue with Google/Microsoft" (OIDC — you already have the validation code, this direction just means *you're* the relying party against *their* IdP instead of the other way around).
- **MFA**: TOTP first (cheap, standard), WebAuthn/passkeys second (matches the "as secure as Proton" positioning — passkeys are what Proton itself has been pushing users toward).
- **Sessions**: short-lived signed session cookie for the web app + the existing bearer-API-key system left exactly as-is for programmatic/CLI access. Don't replace one with the other — they serve different clients.
- **Account recovery**: a recovery-code flow generated at signup (12 single-use codes, shown once, same UX pattern Proton/GitHub/Google all converged on independently — it's the sane way to do recovery when the account is also an encryption-key holder, see Pillar 3).
- **Org/workspace model**: even in Path A, a customer's *account* should support inviting teammates with roles (this already maps onto the existing `admin/analyst/viewer` enum) — "one org, several seats" is the unit you'll actually be billing.
- **Where it lives**: new `POST /v1/auth/signup`, `/login`, `/verify-email`, `/mfa/*`, `/recovery/*` routes; a `password_hash`, `mfa_secret`, `email_verified_at` set of columns on `User`; the `web/` frontend I built gets a real signup/login page in front of `app.html` instead of assuming you already have a key.

## Pillar 2 — Privacy architecture (the real "Lumo" part)

Be precise about what can and can't be zero-access, because RAG and zero-access encryption are in genuine tension:

- **The shared/ingested corpus** (documents fed to `connectors/`, chunked and embedded) **must be server-readable in plaintext** — the retrieval and reranking pipeline computes over it. No amount of encryption changes that; this is true for Lumo too (it must read your message to answer it). Protect this layer the conventional way: disk/volume encryption at rest, strict access control, the audit log you already have.
- **What genuinely can be zero-access**, matching what Lumo actually claims: a user's **private conversation history** and **personal (not-yet-shared) uploads**. Concretely: derive a per-user data-encryption key from their password via Argon2id, wrap it with a key-encryption key the server never sees in the clear, and encrypt `QuerySession`/`Feedback` rows (or at minimum the `question` text and any personal document body) client-side before they're stored — the server can process the query in-flight to generate an answer, but can't later browse a user's stored history. This is the same "server can act on it once, can't retain it legibly" model Lumo uses for chat history.
- **Multi-device access** to that encrypted history needs a key-escrow mechanism — the recovery codes from Pillar 1 double as the escrow secret, again matching how Proton does it.
- **Keep, don't lose, the current shared-audit-log feature** — org-wide "everyone on your team sees every search" is a real selling point for compliance-minded teams (legal, journalism, diligence). Just scope its query in Pillar-3-and-beyond to `WHERE tenant_id = :caller_tenant`, never cross-account.

## Pillar 3 — Post-quantum cryptography (the accurate version of what you asked for)

Applied where it actually helps, in order of effort-to-value:

1. **In transit, essentially free**: if you put Cloudflare (or another modern CDN/WAF) in front, hybrid PQC key exchange (X25519 + ML-KEM-768) for TLS 1.3 is already available there — no code change, just correct infra choice. If self-terminating TLS via the existing Caddy service instead, track OpenSSL 3.2+/BoringSSL hybrid-KEM support as it lands in the Go/Caddy TLS stack.
2. **Wrapping the Pillar-2 vault keys**: use a hybrid classical+PQC KEM (ML-KEM alongside X25519, not instead of it — hybrid is the current best practice specifically so a flaw in the newer PQC math doesn't regress security below today's baseline) to wrap the key-encryption key, so a "harvest now, decrypt later" adversary who exfiltrates wrapped keys today can't unwrap them once quantum computing matures. Library-wise: prefer a well-audited implementation (Cloudflare's CIRCL in Go, or `liboqs` via its Python bindings with the caveat that the Python PQC ecosystem is younger and less audited than the Go/Rust ones — a small Go or Rust sidecar handling only this operation is a defensible choice if the rest of the stack stays Python).
3. **Signing, not encrypting**: use ML-DSA to sign the audit log's periodic Iceberg export and release artifacts — cheap to add, gives you a real "post-quantum integrity" claim (a signature you can point at), distinct from the encryption claim.

Do **not** market this as "quantum encryption" externally — say "hybrid post-quantum cryptography," which is what it is and what Proton itself says. The gap between those two phrases is exactly the gap a technically literate enterprise buyer (your most likely early customer, per Go-to-Market below) will check first.

## Pillar 4 — Compliance & legal groundwork

This product already has an unusually strong starting position here — the README's "legal boundary" section and engagement-scoping for dual-use connectors are real compliance infrastructure most startups don't build until forced to. What's still missing before charging money:

- Legal entity formation, Terms of Service, Privacy Policy, a Data Processing Addendum for business customers (counsel-drafted, not generated).
- GDPR/CCPA program: subject-access-request handling, right-to-erasure against an *append-only* audit log (this needs a designed answer — likely crypto-shredding a per-subject key rather than deleting rows, consistent with Pillar 2's key-based approach).
- A takedown/appeals process for AI-generated answers about real people — the OSINT-adjacent nature of this product invites this scrutiny even though the connectors are all public/licensed/consented sources by design.
- Security: a pen test before general availability, a `security.txt` + responsible-disclosure policy, dependency/secret scanning in CI (Dependabot or equivalent — not yet present), SOC 2 Type I as the first enterprise-credibility milestone (Type II after ~6-12 months of Type I controls running), roughly in that order.

## Pillar 5 — Billing & packaging

| Tier | Who | What differs |
|---|---|---|
| Free | Individual, evaluating | `fast` mode only, low rate limit, shared demo corpus, no uploads |
| Pro | Individual power user | All 3 modes, personal uploads, encrypted private history (Pillar 2) |
| Team | Small org | Seats, shared corpus + shared audit log *within the org*, admin console |
| Enterprise | Compliance-sensitive org | SSO (already built), dedicated hosted instance or self-host, SLA, Iceberg audit export (already built) as a contractual deliverable |

Stripe for subscriptions + metered overage on query volume/`max_sources`; map each plan to the existing `slowapi` rate limiter and a new feature-flag check in `query.py`'s mode dispatch (gate `research` mode behind Pro+, for instance). Self-host stays a real, permanently-offered tier, not a bait-and-switch — it's the differentiator in the next section.

## Go-to-market: the actual wedge against Lumo/Perplexity/You.com

Don't compete as "another AI chat with citations" — that's Perplexity's category and it's crowded. Compete on the two things this codebase already does that a general consumer AI assistant structurally can't:

1. **Self-hostable, so "zero-access encryption on our servers" can become "the data never leaves your servers" for the customers who care most** — legal, journalism, financial diligence, compliance/regulatory teams. That's a strictly stronger privacy claim than Lumo's, and it's already true today, not a roadmap item.
2. **Governance as a product feature, not a compliance afterthought** — the immutable audit log, RBAC/ABAC, admin kill switch, and engagement-scoping are things a compliance officer can point to in a vendor review. Lead sales conversations with the audit trail, not the model.

---

## Phased roadmap

Rough sequencing, not committed dates — ranges assume a small team (2-4 engineers).

**Phase 0 — Foundations (2-4 weeks)**
Add `password_hash`/MFA columns to `User`; signup/login/recovery routes; web signup+login pages in front of `app.html`; dependency/secret scanning in CI; legal entity + ToS/Privacy Policy drafted with counsel.

**Phase 1 — Path A commercial MVP (4-8 weeks)**
Stripe billing + plan gating; per-customer dedicated-instance provisioning (scripted `docker compose` stand-up, not manual); org/seats on top of existing roles; hosted vs. self-host packaging live on the marketing site.

**Phase 2 — Privacy & crypto (4-6 weeks, can run parallel to Phase 1)**
Pillar 2's per-user encrypted conversation vault; recovery-code escrow; hybrid PQC key wrapping (Pillar 3.2); CDN/WAF in front for PQC-in-transit "for free" (Pillar 3.1); ML-DSA signing of the audit export (Pillar 3.3).

**Phase 3 — Trust & scale (ongoing from ~month 3)**
Pen test → SOC 2 Type I; tenant-scoped audit log queries once any shared-deployment tier exists; begin the Path B multi-tenant migration *only* once a specific customer or cost pressure justifies it — Postgres RLS first, Neo4j isolation strategy decided at that point based on actual tenant count and Enterprise-license economics at the time.

**Phase 4 — Growth**
SOC 2 Type II; expand SSO/IdP coverage beyond Keycloak (Okta/Auth0/Entra ID, currently untested per the README); case studies from the legal/journalism/diligence beachhead; evaluate QKD only if a specific customer's threat model and budget genuinely calls for point-to-point dedicated-fiber links — realistically not before this product has enterprise customers asking for it by name.

---

## Decisions I can't make for you

- **Path A vs. Path B**, and if A, hosted-only / self-host-only / both from day one.
- **Target buyer for launch** — the plan assumes legal/journalism/diligence/compliance teams as the wedge; confirm or redirect before Go-to-Market copy gets written.
- **Budget/team size** — the phase estimates assume 2-4 engineers; a solo build stretches every phase 2-3x.
- **First compliance certification to pursue** — SOC 2 is the default enterprise ask in the US; HIPAA/FedRAMP/ISO 27001 are different (and larger) commitments if the buyer profile turns out to need one of those instead.
