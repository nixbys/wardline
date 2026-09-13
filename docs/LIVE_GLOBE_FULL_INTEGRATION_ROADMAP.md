# Live Globe: full-fidelity integration roadmap

*Written 2026-09-13, after cloning the actual upstream source (not just its README) to check what "integrate everything it has to offer" really means to build. Every claim below points at real code in [bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view) (commit `61db945`), not the project's own marketing summary.*

*See [`MASTER_ROADMAP.md`](MASTER_ROADMAP.md) for how this track relates to the other two roadmap documents in this repo and what's actually being worked on next across all three.*

## Why this document exists

The initially-approved plan (see the PR that added `api/routers/globe.py`, `connectors/usgs_earthquakes.py`, `connectors/nasa_firms.py`) treated God's Eye View as a small vanilla-JS learning tool and scoped a from-scratch, wardline-themed Cesium app against a handful of live-proxy endpoints. Cloning the real repository changed that assessment:

- **~116,000 lines of JS**, not a sketch. A cinematic camera/scene director, a "cockpit mode" with its own HUD/vision policy, CCTV focus policy, first-run experience, keyless-geocoding fallback chains, an internal module-boundary enforcement tool (`scripts/check-package-boundaries.mjs`) — a mature, actively-maintained application.
- **~20 live data sources**, each with its own license/ToS (see its `DATA_SOURCES.md`): OpenSky, adsb.lol, AISStream, CelesTrak, The Space Devs, Esri, USGS, Overpass/OSM, TomTom, Photon, Nominatim, Open-Meteo, Google News RSS, GDELT, three different municipal CCTV catalogs, GBFS bikeshare, Radio Browser, Re:Earth terrain — plus bundled datasets, one of which (**TeleGeography submarine cables, CC BY-NC-SA — NonCommercial**) the project's own docs say must be removed for commercial use.
- **It's explicitly built to be consumed as a library.** `package.json`'s `exports` map exposes `./application`, `./application/viewer`, `./layers/{flights,vessels,earthquakes,firms,military}`, `./ui/*`, and Node-only `./server/providers/*` as documented subpath imports, with a boundary-checking script enforcing that contract. This is the intended integration seam — not vendoring/copy-pasting files.
- **Theming is far more tractable than expected.** `src/ui/styles/foundation.css` defines the whole visual identity as `:root` CSS custom properties (`--accent`, `--glass-bg`, `--glass-border`, `--text-primary/secondary/dim`, `--panel-radius`, `--font-sans/mono`) — a naming scheme close enough to Wardline's own `web/assets/css/tokens.css` that re-theming is realistically a values-only override layer, not a rewrite of ~19 component stylesheets.

None of this fits in one session. This document is the detailed plan the approved scope asked for when that became clear, so the work can proceed in deliberate, reviewable phases instead of one unbounded effort.

## Already shipped (Phase 0 — this branch)

- `src/wardline/api/routers/globe.py`: a from-scratch, wardline-native proxy for 4 of the ~20 sources above (opensky, celestrak, aisstream, tomtom) plus an OpenAI Realtime ephemeral-session endpoint, all public/rate-limited.
- `src/wardline/connectors/usgs_earthquakes.py` + `nasa_firms.py`: real citable-document connectors for the two discrete-event sources, through the normal ingestion/citation pipeline.
- A lean, original (not vendored) Cesium/Vite frontend at `globe/`, styled with Wardline's own tokens, consuming the endpoints above. *(Tracked as the next commit on this branch — see repo state.)*

This stays as-is; it is not wasted work. Phase 2 below explicitly reconciles it with the fuller architecture rather than discarding it.

## Recommended architecture for full parity

**Fork, don't vendor; consume via its own exports; run its Node providers as a sidecar.**

1. **Real GitHub fork**, not a copy-pasted vendor tree: `nixbys/gods-eye-view` forked from `bilawalsidhu/gods-eye-view`, `upstream` remote configured so improvements/fixes upstream ships keep flowing in via ordinary `git fetch upstream && git merge`. A copy-paste vendor of a 116K-line, actively-developed project would fork silently on day one and rot; a real fork is the only version of "bring this in" that stays maintainable.
2. **Wardline changes live as a small, isolated diff on top of the fork** — not scattered edits: a new `src/ui/styles/wardline-theme.css` overriding `foundation.css`'s custom properties (see the theming finding above), and whatever minimal wiring lets its provider layer read config the way Wardline's `Settings` already models it (see Phase 3). Small diff = easy to keep rebasing on upstream.
3. **`wardline/globe/`'s Vite app depends on the fork as a git dependency** (`"gods-eye-view": "github:nixbys/gods-eye-view#<pinned-commit-or-branch>"`) and imports its real, tested code via the documented subpaths (`gods-eye-view/application`, `gods-eye-view/ui/shell`, `gods-eye-view/layers/vessels`, etc.) — full fidelity to upstream's actual rendering/interaction logic, not a reimplementation racing to keep up with it.
4. **A new `docker/globe-server/` Node sidecar** runs the fork's real `server/providers/*` (aircraft, vessels, firms, traffic, cctv, overpass, places, radio, gbfs, openai, military-installations, regional) directly, imported via those same `exports` — the same isolation pattern this repo already uses for `docker/toolrunner/` (a non-root, single-purpose sidecar container, not code merged into `api`/`worker`). Caddy gains a route (`/globe-api/*` → `globe-server`), or `api/routers/globe.py` becomes a thin authenticated/rate-limited reverse-proxy in front of it — decide which in Phase 3 (see open decision below).
5. **`api/routers/globe.py` and the two connectors from Phase 0 don't get thrown away.** Once the sidecar covers aircraft/vessels/traffic with full fidelity, `globe.py`'s hand-rolled versions of those three become redundant and should be removed in favor of the sidecar; its `/realtime-session` endpoint and the two USGS/FIRMS *connectors* (citable-document ingestion, a Wardline-specific concept the upstream project has no equivalent of) stay, since nothing upstream replaces them.

### Why fork instead of the alternatives

| Option | Verdict |
|---|---|
| **Fork + subpath-export dependency + Node sidecar** (recommended) | Full fidelity, stays updatable, isolated blast radius, matches the project's own intended consumption pattern. |
| Vendor (copy files into this repo) | Guaranteed drift from day one on a fast-moving 116K-line project; every upstream fix has to be hand-ported forever. |
| Depend on `bilawalsidhu/gods-eye-view` directly, no fork | Works only if zero changes are ever needed (no theming, no config wiring) — not realistic once theming/provider-config integration starts. |
| Full vendor port of the entire app (cockpit, scenes, CCTV, everything) in one push | The option explicitly ruled out already — not realistic in any single session at this scale. |

## Licensing/compliance groundwork (do this before enabling anything customer-facing)

Same posture this repo already takes with `shodan`/`nmap` in the README's "Authorized pentesting connectors" section — real review before anything reaches a paying customer, not after:

- **TeleGeography submarine-cable dataset (CC BY-NC-SA, NonCommercial) must be removed or gated** before any commercial use of Wardline that includes the globe — it's bundled data, not a live call, so this is a one-time deletion/gate in the fork, not a runtime check. Track it as its own checklist item; don't let it ride along silently.
- **Per-source ToS review**, mirroring `DATA_SOURCES.md`'s own table: Google Maps Platform (proprietary, billing), TomTom (free tier request-capped), Google News RSS (personal/noncommercial use only — flag if Wardline's research mode ever surfaces this to a paying seat), GDELT (citation + link required), TfL JamCams (attribution required by ToS, not just courtesy). Attribution requirements are especially load-bearing here — several are "required," not "requested."
- **Attribution surface**: upstream already renders required credits via `viewer.creditDisplay.addStaticCredit` (Cesium's own on-globe credit line) plus a "Data attribution" lightbox — keep both intact through the fork/theme changes rather than styling them away, since several of these (TfL, Google) are contractually required, not cosmetic.
- Extend Wardline's own `THIRD_PARTY_NOTICES.md`-equivalent (Phase 0 already planned one for the MIT code license) to also carry this per-dataset table, not just "MIT, see LICENSE."

## Phased implementation plan

Each phase is independently shippable and reviewable — land as its own PR, same convention as the rest of this repo's history.

**Phase 1 — Fork + theming spike (small, low-risk, validates the core assumption)**
- Fork the repo (needs explicit go-ahead — see "Decisions needed" below).
- Add `src/ui/styles/wardline-theme.css` remapping `foundation.css`'s custom properties to Wardline's palette; run the fork standalone (`npm run dev`) and confirm the re-theme actually looks like Wardline without breaking any component CSS that assumes the original values.
- Deliverable: a screenshot/PR showing the real upstream app, wardline-themed, running standalone (not yet wired into `wardline/globe/`).

**Phase 2 — Wire one real layer end-to-end through the sidecar**
- Stand up `docker/globe-server/` importing just `gods-eye-view/server/providers/aircraft` (or vessels — whichever has the simplest config surface) and `gods-eye-view/layers/aircraft` on the frontend side.
- Retire `globe.py`'s hand-rolled `/opensky` route once the sidecar's real version is live and reachable, so there's exactly one implementation of that proxy, not two drifting in parallel.
- Deliverable: real aircraft rendering via upstream's actual code, through Wardline's infra, wardline-themed.

**Phase 3 — Expand to the rest of the live sources**
- Repeat Phase 2's pattern per source: vessels, satellites (CelesTrak/SGP4 via `satellite.js`, already an upstream dependency), traffic, earthquakes/FIRMS *for the globe's live view* (distinct from — and not a replacement for — the citable-document connectors from Phase 0, which stay as the RAG-ingestion path).
- **Open decision to make here, not before**: does `api/routers/globe.py` become a thin authenticated/rate-limited reverse proxy in front of `globe-server` (keeps Wardline's existing security-header/rate-limit/kill-switch posture at the edge for every layer), or does Caddy route `/globe-api/*` straight to the sidecar (simpler, but that traffic bypasses Wardline's own middleware stack)? Recommend the former for consistency with how every other public endpoint in this app is fronted, but it's a real tradeoff (extra hop) worth deciding deliberately, not by default.
- Config wiring: map Wardline's `Settings` (already extended in Phase 0 for `OPENSKY_CLIENT_ID/SECRET`, `AISSTREAM_API_KEY`, `TOMTOM_API_KEY`) through to `globe-server`'s environment, plus the sources Phase 0 didn't cover (Google Maps/Places, CelesTrak needs no key, The Space Devs, Overpass/OSM, Photon, Nominatim, Open-Meteo, Google News RSS, GDELT, the three CCTV catalogs, GBFS, Radio Browser).

**Phase 4 — Cockpit mode, scenes, and the rest of the UI shell**
- Import `gods-eye-view/ui/shell`, `gods-eye-view/scenes`, `gods-eye-view/ui/cockpit` and wire Wardline's theme through the parts of the CSS that Phase 1's spike didn't already cover (cockpit-specific overlays, command dock, radio panel).
- Voice control: swap Phase 0's minimal realtime-session endpoint for upstream's actual `server/providers/openai` + its 28 voice tools, once the sidecar exists to host it.

**Phase 5 — Licensing pass + production readiness**
- Execute the "Licensing/compliance groundwork" checklist above for real (dataset removal/gating, ToS sign-off, attribution audit).
- Add `docker/globe-server/` to `docker-compose.yml` properly (health check, resource limits, matching the existing service conventions), and a README section documenting the whole stack the way `toolrunner`'s profile is documented today.

## Status

- **Fork created: [nixbys/gods-eye-view](https://github.com/nixbys/gods-eye-view)** (public, `isFork: true`, parent `bilawalsidhu/gods-eye-view`, default branch `main`). Nothing has been pushed to it yet — Phase 1 (the theming spike) is the first work that actually lands commits there. Add an `upstream` remote pointing at `bilawalsidhu/gods-eye-view` before starting Phase 1, so `git fetch upstream` stays available for pulling improvements.
- **Phase 0** (this repo's `globe/`, wardline-themed, against the endpoints in `api/routers/globe.py`) is being built in parallel on `feat/live-globe-integration` — see that branch for current status.

## Decision still open

**Pace**: land Phase 1 (the fork-side theming spike) next, or hold it and keep iterating on Phase 0's lean build for a while first? Both are legitimate; this doc doesn't assume an answer — ask before starting Phase 1's implementation work.
