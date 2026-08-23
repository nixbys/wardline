# wardline web console

A static front end for the wardline API — a marketing page (`index.html`) plus a
working chat-style research console (`app.html`) that talks to the real
endpoints in [`src/wardline/api/routers/`](../src/wardline/api/routers/). No
build step, no framework, no CDN dependency: plain HTML/CSS/JS you can open
directly or serve from anything.

The visual identity is monochrome and deliberately its own: a near-black canvas, translucent glass panels (`backdrop-filter: blur`) instead of solid colored cards, a single white/near-black accent rather than a brand hue, and a centered pill-shaped composer + sidebar/thread chat layout. The component vocabulary underneath — small consistent radii, quiet 1px borders instead of heavy shadows, restrained color used only for state (accent/success/warning/danger), segmented controls, badges, label-above-input form fields — follows the Flux (Livewire's UI kit) tradition without copying any one product's specific look.

Both light and dark themes are supported (`assets/js/theme.js`), following
the OS preference by default with a manual override persisted per-browser.

## Running it

Any static file server works — the app is pure client-side JS hitting the
API over `fetch`.

```bash
cd web
python3 -m http.server 4000
# → http://localhost:4000/index.html  (landing page)
# → http://localhost:4000/app.html    (research console)
```

The API itself needs to allow this origin via CORS if you serve the two on
different ports (`wardline` doesn't enable CORS by default — see
`src/wardline/api/main.py` — add a `CORSMiddleware` there for the origin you
serve this from if you hit cross-origin errors in the browser console).

## Connecting to a real backend

1. Stand up the API per the repo root [README](../README.md#setup):
   `docker compose -f docker/docker-compose.yml up -d`, run migrations.
2. Either self-serve or admin-issued:
   - **Self-serve** (the default path now): open `login.html`, switch to the
     "Sign up" tab, and create an account. `EMAIL_MODE=mock` (the default)
     logs the verification link to the API's own logs instead of sending a
     real email — `docker compose -f docker/docker-compose.yml logs api`
     and copy the `token=...` value into `verify-email.html?token=...`
     (or just call `POST /v1/auth/verify-email` directly), then log in.
   - **Admin-minted**, for scripts/CI rather than a person:
     ```bash
     docker compose -f docker/docker-compose.yml run --rm api \
       python -m wardline.cli create-admin-user you@example.com
     ```
     which prints an API key once — paste it into `app.html`'s connection
     settings (the gear icon) instead of going through `login.html`.
3. Ask a question. The console calls `POST /v1/query` with the selected mode
   (`fast` / `auto` / `research`, matching `QueryRequest.mode`) and renders
   the answer, confidence, an `insufficient_evidence` warning when the
   pipeline says so, and the returned `sources` list.

Everything the UI shows is either live from the API or explicitly
client-only:

| Feature | Backed by |
|---|---|
| Sign up / log in / MFA | `POST /v1/auth/signup`, `/login`, `/mfa/*` (`login.html`) |
| Password reset / email verification / invite acceptance | `POST /v1/auth/password/*`, `/verify-email`, `/accept-invite` (`reset-password.html`, `verify-email.html`, `accept-invite.html`) |
| Pricing page / plan limits shown | `GET /v1/billing/plans` (`pricing.html`) — same numbers the server enforces, never a separate hard-coded copy |
| Subscribe / manage billing | `POST /v1/billing/checkout`, `/portal` (`pricing.html`, `app.html`'s settings modal) |
| Ask a question | `POST /v1/query` |
| Sources / citations per answer | `sources` field of the query response |
| Thumbs up/down on an answer | `POST /v1/feedback` |
| "Inspect session" panel | `GET /v1/session/{id}` |
| Upload a document | `POST /v1/documents/upload` (multipart) |
| Connection status dot | `GET /healthz` |
| Chat history sidebar | **client-side only** — `localStorage`, keyed by the `session_id` each query returns. `GET /v1/session/{id}` doesn't echo the rendered answer back (only audit metadata: retrieved chunk ids, latency, token cost), so the transcript itself lives in the browser, not the server. |

No telemetry, no third-party requests — the only network calls this page
makes are to the API base URL you configure.

## File layout

```
web/
├── index.html              marketing/landing page
├── app.html                research console (the actual app)
├── login.html              sign up / log in / MFA challenge
├── verify-email.html       lands here from the emailed verification link
├── reset-password.html     request a reset, then (with ?token=) set a new password
├── accept-invite.html      lands here from an admin's invite link
├── pricing.html            plan cards, reads live from GET /v1/billing/plans
└── assets/
    ├── css/
    │   ├── tokens.css       color/spacing/typography variables, light+dark
    │   ├── base.css         resets and global element styles
    │   ├── components.css   shared "Flux-style" component classes
    │   ├── landing.css      index.html-only layout
    │   ├── app.css          app.html-only layout
    │   ├── auth.css         shared centered-card layout for the four auth pages
    │   └── pricing.css      pricing.html-only layout
    └── js/
        ├── theme.js          light/dark toggle, shared by every page
        ├── api.js            fetch wrapper for the wardline API
        ├── app.js            research console interactivity
        ├── auth-pages.js     login/signup/verify/reset/invite logic
        └── pricing.js        plan cards + checkout
```

## Extending it

- New component → add a class to `components.css` following the existing
  naming (`.thing`, `.thing--variant`, `.thing__part`), not a page-specific
  override.
- New page → include `tokens.css`, `base.css`, `components.css`, then a
  page-specific stylesheet for layout only.
- New endpoint → add one method to `WardlineApi` in `assets/js/api.js`; keep
  the request/response mapping there so page scripts never call `fetch`
  directly.
