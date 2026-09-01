# IsItTrue

Paste (or attach an image of) a WhatsApp forward, news snippet, or claim
someone told you and get a plain-language verdict per claim — Supported,
Refuted, or Unverifiable — plus a one-line summary. Powered by the extract →
verify → aggregate → synthesize fact-checking pipeline, reused from this
workshop's `systems/FactCheckerAgent` prototype, wrapped in a small API
with caching and cost-containment guardrails so it's safe to run publicly
on a free-tier budget. Also ships a desktop browser extension that
right-clicks selected text or an image on any page (including WhatsApp Web)
to check it without copy-pasting.

This folder is self-contained: it has no dependency on anything outside
itself, and can be copied out and pushed as its own standalone repo without
any code changes.

## Directory layout

```
is-it-true/
    backend/
        main.py                 # FastAPI app: CORS + mounts /api routes
        pipeline_service.py      # run_fact_check_stream() -- extract/verify/aggregate/synthesize,
                                    # yielding progress events; run_fact_check() drains it for JSON callers
        image_utils.py            # downscales oversized uploads before they reach Gemini
        config.py                # env-driven settings
        redis_client.py          # shared Redis connection (falls back to in-memory if unset)
        api/
            routes.py              # POST /api/check (JSON) + POST /api/check/stream (SSE),
                                      # GET /api/health, GET /api/admin/stats
            schemas.py              # response models for the /api/check API boundary
        tests/                   # pytest, Gemini calls mocked -- no API key needed to run these
        conftest.py                # pipeline/ on sys.path for tests + in-memory state reset between tests
        pytest.ini
        .coveragerc
        requirements-dev.txt      # requirements.txt + pytest/pytest-cov, kept out of the production image
        limits/
            identity.py            # cookie-or-IP anon id for rate limiting
            rate_limiter.py         # per-user daily cap + global daily kill-switch
        cache/
            report_cache.py        # content-hash cache of full reports (Redis, 30-day TTL)
        pipeline/                # copied verbatim from systems/FactCheckerAgent -- do not
            shared/                  # hand-edit; re-copy from source if it changes there
            extraction/
            verification/
            reporting/
            common/
        requirements.txt
        Dockerfile
        .dockerignore            # keeps .env, tests/, __pycache__ etc. out of the built image
        .env.example
    frontend/
        index.html               # textarea + attach-image/paste + "Check this" button + result cards
        style.css
        app.js                    # fetch() to the backend; edit API_BASE_URL before deploying
    extension/                # desktop browser extension (Manifest V3, unpacked/dev only)
        manifest.json            # contextMenus + storage permissions, <all_urls> host permission
        background.js             # registers "check this text/image" context menu entries
        results.html                # bundled results page opened in a new tab
        results.js                   # calls the backend directly; edit API_BASE_URL before use
        results.css
        icons/                        # 16/48/128px, referenced by manifest.json and the Store listing
    PRIVACY.md                # required before Chrome Web Store submission -- must be hosted at a public URL
    STORE_LISTING.md          # draft listing copy + permission justifications for the Store submission
    DEPLOYMENT.md
    LICENSE
    .gitignore
```

## Run locally

Backend:

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env    # fill in GEMINI_API_KEY; leave REDIS_URL unset for local dev
uvicorn main:app --reload --port 8000
```

Frontend (in a second terminal):

```bash
cd frontend
python -m http.server 5500
```

Open `http://localhost:5500`. `app.js`'s `API_BASE_URL` already points at
`http://localhost:8000`, and the backend's default `CORS_ORIGINS` includes
`http://localhost:5500` — no edits needed for local dev. Attach an image via
the "📎 Attach image" button or by pasting a screenshot (Ctrl+V) directly
into the text box.

The web app (and the browser extension's results page) calls
`POST /api/check/stream` (Server-Sent Events) so claim cards fill in one at
a time as each finishes verifying, instead of one long silent wait.
`POST /api/check` (plain JSON, same shape as before) still exists
unchanged for any other caller that wants a single blocking response.

Without `REDIS_URL` set, the cache and rate limiters fall back to an
in-memory store — fine for trying it out on one machine, not for production
(state resets on every restart, and isn't shared if you ever run more than
one backend instance).

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
pytest --cov=. --cov-report=term-missing
```

Every Gemini call is mocked (`unittest.mock.patch` on
`extraction.claim_extractor.generate_content` /
`verification.verifier.generate_content`, or on `pipeline_service`'s own
`extract_claims`/`verify_claim`/`synthesize_report` for the
orchestration-level tests) — the suite runs in ~2 seconds, makes no real
API calls, and needs no `GEMINI_API_KEY` to pass. Coverage sits around
80%; the gap is almost entirely `if __name__ == "__main__":` manual-demo
blocks in the copied `pipeline/` modules, not untested logic. Notably,
`tests/test_claim_extractor.py` and `tests/test_verifier.py` are
regression tests for two real bugs found and fixed during manual testing
this project went through (duplicate model-invented claim ids colliding
downstream, and the confidence-floor clamp).

### Browser extension (desktop, unpacked/dev only)

1. In Chrome/Edge, go to `chrome://extensions`, enable "Developer mode",
   click "Load unpacked", and select `extension/`.
2. Copy the extension's id from that page (looks like
   `chrome-extension://abcdefghijklmnop...`) and add it to the backend's
   `CORS_ORIGINS` (comma-separated alongside the frontend's origin), then
   restart the backend.
3. `extension/results.js`'s `API_BASE_URL` defaults to
   `http://localhost:8000` — edit it if your backend runs elsewhere.
4. Select text on any page (or right-click an image) → "Check this
   text/image with IsItTrue" → a results tab opens and shows the
   verdicts.

Unpacked extension ids can change across reloads unless the manifest pins a
`key` — for local testing just re-copy the id into `CORS_ORIGINS` if it
changes. Right-clicking an image fetches its bytes from the page it's on;
some sites' own CORS policy may block that fetch (a known limitation, not
something this app controls) — `results.js` shows a clear message and
suggests using the web app's attach-image option instead when that happens.

## Cost containment (why this is safe to make public on a free tier)

1. **Content-hash cache** (`cache/report_cache.py`) — identical text and/or
   image bytes are a cache hit with zero Gemini calls, keyed by
   `sha256(text + image_bytes)`, 30-day TTL. This is the biggest lever: the
   same viral forward (text or image) gets shared by many people, and only
   the first person's check costs anything.
2. **Per-browser daily cap** (`DAILY_USER_CAP`, default 5/day) — a cookie
   (falling back to a hashed IP before the cookie is set) blunts casual
   abuse from one browser.
3. **Global daily kill-switch** (`GLOBAL_DAILY_CALL_CAP`, default 500/day)
   — a site-wide counter of actual Gemini calls made, weighted by
   `IMAGE_CALL_WEIGHT` (default 4) for any request that includes an image,
   since an image-bearing call costs meaningfully more tokens than a
   text-only one. Once hit, every new (non-cached) request gets a `503`
   regardless of who's asking. This is the real backstop — it holds even if
   the per-user cap is bypassed (cleared cookies, different networks) or
   usage spikes from many distinct users at once.
4. **Input caps** — `MAX_INPUT_CHARS` (default 3000) for text,
   `MAX_IMAGE_BYTES` (default 5MB) and an allowed-mime-type set
   (`image/jpeg`, `image/png`, `image/webp`) for images — bound the
   worst-case cost and reject junk uploads before they reach Gemini.
5. **Selective image re-attachment** (`pipeline_service.run_fact_check_stream`)
   — the image is only re-sent during verification for claims the
   extraction step flagged `needs_image=true` (claims about the image's own
   visual content, e.g. a diagram's label). Claims that are just general
   facts printed as text in the image don't need it looked at again, so
   most requests carry the image on 1-2 calls instead of every one.
6. **Belt-and-suspenders**: also set a billing/budget alert directly on the
   Google AI Studio / Gemini API project (e.g. at $5 and $10) — an
   out-of-band safety net independent of this app's logic.

Tune the caps via env vars once you have a sense of real usage and actual
Gemini spend per request.

## Latency

Image checks are the slow path -- larger prompts, and (before the fix
above) the image used to be re-sent on every verification call. Two things
address this specifically:

- **Selective re-attachment** (above) cuts most requests from `N+1` image
  transmissions down to close to 1.
- **`image_utils.downscale_if_oversized`** resizes (never recompresses) any
  upload whose longest side exceeds `MAX_IMAGE_DIMENSION` (default 1600px)
  before it reaches Gemini -- large phone-camera photos are the main
  target; already-reasonably-sized screenshots/infographics pass through
  untouched so small printed text stays legible for extraction.

Neither of these makes the wait disappear, so `/api/check/stream` also
streams progress (claims found → each verdict as it resolves → summary)
so there's something on screen the whole time instead of one long blank
wait.

## Observability

- **Logs** (`logging.basicConfig` in `main.py`) — every request/response
  logs an `[article_id-prefix]` line (input size and presence, cache hits,
  verdict counts, rate-limit rejections and which cap was hit), at INFO/
  WARNING. Third-party libraries (`google_genai`, `httpx`) are dialed down
  to WARNING so they don't drown this out. On Render/Fly.io this shows up
  in the platform's own log viewer for free — no extra infra.
- **`GET /api/admin/stats`** — today's global Gemini-call usage against
  `GLOBAL_DAILY_CALL_CAP`, i.e. "how close are we to the daily cost cap
  right now." Gated by an `X-Admin-Token` header checked against
  `ADMIN_TOKEN` (`secrets.compare_digest`, not `==`, to avoid a timing
  side-channel). **Disabled (404) until `ADMIN_TOKEN` is set** — it isn't
  a real auth system, just enough to keep this off the open internet by
  default. Per-user/distinct-visitor counts aren't tracked (only
  per-browser counters, no set of all ids) — a possible future addition,
  not built now.

## Deploying

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full step-by-step runbook
(accounts, provisioning, env vars, CORS wiring, a production smoke-test
checklist). Short version: `backend/Dockerfile` → Render or Fly.io;
`frontend/` → Vercel or Netlify; Redis → Upstash; then point `CORS_ORIGINS`
and `app.js`'s `API_BASE_URL` at each other's real deployed URLs.

## Known limitations (acceptable for v1, worth knowing about)

- Rate-limit identity (cookie/IP) is a soft signal, not a real account
  system — it can be bypassed. The global daily cap is the actual backstop.
- No durable analytics beyond what Upstash/Render's own dashboards show;
  add a proper database if you need more than that later.
- `pipeline/` only uses the model's own knowledge, same as the original
  prototype — no live web search, so very recent events may come back
  `UNVERIFIABLE` rather than checked against a source. Time-sensitive facts
  (prices, scores, weather) are explicitly steered to `UNVERIFIABLE` in
  `pipeline/verification/prompts.py` rather than risk a confidently wrong
  verdict based on stale training data.
- The browser extension treats a right-click on text and a right-click on
  an image as two independent, instant checks (by design) -- it never
  combines a message's caption and image into one request the way pasting
  both into the web app does. Both flows stream progress the same way the
  web app does.
- The browser extension is unpacked/dev-mode only (no Chrome Web Store
  listing), and its right-click-image flow can be blocked by a source
  site's own CORS policy (see the extension setup section above).
- No mobile/WhatsApp Business API integration yet — this phase targets
  desktop (web app + browser extension) only.
