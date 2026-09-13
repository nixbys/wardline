# Wardline Live Globe

A live 3D CesiumJS view of public flight, vessel, satellite, and traffic
data, proxied through wardline's own API (`src/wardline/api/routers/globe.py`)
so no visitor needs their own API keys. Public, no login required — the
same trust tier as `web/index.html`.

**This is an original build, not a vendored copy**, inspired by
[bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view)
(MIT) — see the credit line in the HUD and `THIRD_PARTY_NOTICES.md` at the
repo root. It's intentionally a much smaller slice of what that project
does: aircraft, satellites, vessels, traffic (click-to-query), and a
two-tool voice control (fly-to, layer toggle), not its cinematic camera
system, cockpit mode, CCTV, or the other ~15 data sources it also
integrates. **[`docs/LIVE_GLOBE_FULL_INTEGRATION_ROADMAP.md`](../docs/LIVE_GLOBE_FULL_INTEGRATION_ROADMAP.md)**
at the repo root is the detailed plan for bringing in the rest, via a real
fork ([nixbys/gods-eye-view](https://github.com/nixbys/gods-eye-view)) —
this app is that plan's "Phase 0."

## Running it

```bash
npm ci
cp .env.example .env   # only needed if the wardline API isn't at localhost:8000
npm run dev            # http://localhost:4173
```

The wardline API needs to allow this origin via CORS if served from a
different port in dev (same caveat `web/README.md` documents for that
frontend) — `wardline` doesn't enable CORS by default.

For `GET /v1/globe/config` to report every layer as usable, the API needs
the relevant optional settings configured (see `.env.example` at the repo
root): `OPENSKY_CLIENT_ID`/`SECRET`, `AISSTREAM_API_KEY`, `TOMTOM_API_KEY`,
`OPENAI_API_KEY`. Aircraft and satellites work with none of these set.

## Deployment

Built assets (`npm run build` → `dist/`) are meant to be served at a
`/globe/` path alongside `web/`'s own root — e.g. a reverse proxy (Caddy)
mapping `/` → `web/` and `/globe/` → this app's `dist/`. `vite.config.js`'s
`base: "/globe/"` matches that. Nothing in `docker-compose.yml` serves
either frontend yet (see the root README's Production readiness section) —
deploy this the same manual way `web/` is deployed today.

## File layout

```
globe/
├── index.html          entry point (Cesium container + HUD shell)
├── vite.config.js       base path + vite-plugin-cesium
├── src/
│   ├── main.js           bootstraps the Cesium viewer, wires layers + HUD + voice
│   ├── api.js             thin client for /v1/globe/*
│   ├── hud.js             layer toggles, status, required attribution
│   ├── voice.js           OpenAI Realtime WebRTC client (fly_to, toggle_layer tools)
│   ├── style.css          imports web/assets/css/tokens.css, then page-local layout
│   └── layers/
│       ├── aircraft.js     OpenSky, polled per-viewport
│       ├── satellites.js   CelesTrak TLEs, propagated client-side with satellite.js
│       ├── vessels.js      AISStream, polled per-viewport, opt-in (see main.js)
│       └── traffic.js      TomTom, click-to-query (not a continuous layer)
```

## Attribution

Every live source here carries its own license/citation expectation
(OpenSky's non-commercial research license, CelesTrak's citation request,
TomTom's "credit when live" clause, Esri's basemap credit). These render
in the HUD's attribution line and Cesium's own on-globe credit widget —
keep both intact; don't style them away. See the roadmap doc's "Licensing
groundwork" section before any commercial use of a fuller integration.
