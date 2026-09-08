# Post-quantum TLS in transit

This is the accurate, buildable version of "quantum encryption" for traffic
between a browser (or API client) and this deployment — see
[`COMMERCIALIZATION_ROADMAP.md`](COMMERCIALIZATION_ROADMAP.md)'s "quantum
encryption" section for why true QKD isn't a real option for a product like
this, and Pillar 3 for the full picture (this covers 3.1 only; 3.2's vault
key wrapping and 3.3's audit-export signing are separate, already-shipped
pieces — see [`security/vault.py`](../src/wardline/security/vault.py) and
[`storage/iceberg_signing.py`](../src/wardline/storage/iceberg_signing.py)).

**The threat this defends against**: "harvest now, decrypt later" — an
adversary recording today's encrypted TLS traffic to break it open once a
sufficiently capable quantum computer exists. Classical TLS 1.3 key exchange
(X25519 alone) is not vulnerable to any *classical* attack, but it is exactly
the kind of RSA/ECC-based exchange Shor's algorithm threatens once quantum
computing matures — recorded traffic today stays exposed to that future
attack unless the key exchange itself is upgraded.

## Recommended: a CDN/WAF in front (no code or infra change here)

Put a modern CDN/WAF — Cloudflare is the concrete example the roadmap
names, and comparable providers are catching up — in front of this
deployment's reverse proxy. Cloudflare already negotiates a hybrid
X25519+ML-KEM-768 key exchange for TLS 1.3 today, for any origin behind it,
with **no application code change and no change to this repo's own TLS
termination**. This is the effort-to-value winner precisely because it's
free: correct infrastructure choice, not new engineering.

This is also consistent with — and complementary to — the
self-hosted-vs-hosted positioning in the roadmap's go-to-market section: a
hosted customer gets this automatically as part of the platform; a
self-hosted customer who fronts their own deployment with a CDN/WAF gets the
identical property.

## Alternative: self-terminating TLS via the bundled Caddy service

`docker/Caddyfile` terminates TLS directly (auto-provisioned Let's Encrypt
certs) for deployments that don't want a third-party CDN/WAF in the path at
all — the stronger self-hosted privacy story this product's whole go-to-market
leans on ("the data never leaves your servers", per the roadmap's own
framing) is weakened somewhat by adding a CDN in front, even one with a
strong zero-trust reputation, since it becomes another party that sees
plaintext at the TLS edge.

Caddy's own Go TLS stack does not yet negotiate hybrid PQC key exchange for
TLS 1.3 as of the version currently pinned — there's no `Caddyfile` directive
to opt into it because the underlying support in Caddy's build isn't there
yet, not because of a missing config option. Track:

- Go's `crypto/tls` package: `X25519MLKEM768` landed as a supported curve
  starting in Go 1.24. Caddy needs to be built against a Go toolchain that
  includes it (and to actually advertise/select it — check Caddy's own
  release notes for hybrid-KEM support specifically, not just "built with
  Go 1.24+").
- Once confirmed, bump the pinned Caddy image in `docker-compose.yml` — this
  then applies automatically, no `Caddyfile` change needed.

Until that lands, self-terminating deployments get standard (non-hybrid)
TLS 1.3 — not weaker than what almost every other product on the market
offers today, just not yet PQC-hybrid.

## What this is not

Don't market this as "quantum encryption." Say "hybrid post-quantum
cryptography," which is what it actually is. A technically literate
enterprise buyer — this product's most likely early customer per the
roadmap's go-to-market section — will check that distinction first.
