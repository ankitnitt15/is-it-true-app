# Deploying IsItTrue to production

This is an execution checklist, not background reading — follow it in
order. It assumes you're starting from scratch on every platform (no
existing Render/Upstash/Vercel accounts). Everything here is free-tier.

None of this touches GitHub for you — pushing this code to your own
GitHub account is something you do yourself from wherever you're doing
that. Steps 4 and 5 below assume the code is already on GitHub by the
time you get to them.

## -1. Run the test suite one last time

```bash
cd backend && pip install -r requirements-dev.txt && pytest
```

All 39 should pass, no `GEMINI_API_KEY` required (every Gemini call is
mocked). Catches a regression before it ships, not after.

## 0. Clean the folder before you zip/move it

Do this **last**, right before you copy the folder anywhere — not now,
if your backend is still running locally against these files.

```bash
cd apps/is-it-true
rm -rf backend/.venv_test backend/.env
find . -name "__pycache__" -type d -exec rm -rf {} +
```

**Why this matters**: `backend/.env` holds your real `GEMINI_API_KEY`.
`.gitignore` only stops `git` from tracking it — a plain `zip`/`cp` of the
folder includes it regardless. Check it's actually gone before you zip:

```bash
ls backend/.env   # should say "No such file or directory"
```

You'll recreate `.env` locally from `.env.example` any time you want to
run it again; production gets its own copy of these values entered
directly into Render's dashboard (step 4), never committed anywhere.

## 1. Google AI Studio

1. Confirm you have a `GEMINI_API_KEY` (the same one already in your local
   `.env.example`-derived setup). If you don't have one:
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey) →
   create a key.
2. Set a billing alert so a bug or a traffic spike can't run away
   unnoticed: in
   [Google Cloud Console billing](https://console.cloud.google.com/billing) →
   the project backing your API key → **Budgets & alerts** → create a
   budget (e.g. $5) with alert thresholds at 50%/90%/100%. This is a
   backstop *independent* of this app's own `DAILY_USER_CAP`/
   `GLOBAL_DAILY_CALL_CAP` — it should fire only if those somehow fail.

## 2. Upstash (Redis)

1. Sign up at [upstash.com](https://upstash.com) (GitHub/Google login is
   fine).
2. **Create Database** → give it a name → pick the region closest to
   where you'll run the backend (matters a little for latency, not
   correctness) → **Create**.
3. On the database's page, find the **Connect** / **REST/Redis** section
   and copy the connection string starting with `rediss://` (note the
   double-s — that's the TLS variant; Upstash's free tier requires TLS,
   and `redis-py` — already in `requirements.txt` — handles `rediss://`
   natively, no extra setup).
4. Save that string somewhere for step 4 — it's your `REDIS_URL`.

You can sanity-check it works before wiring it into Render:

```bash
cd backend && source .venv_test/bin/activate   # or whichever venv has requirements.txt installed
python3 -c "import redis; r = redis.from_url('PASTE_YOUR_REDIS_URL_HERE'); print(r.ping())"
```

(That `import redis` is the third-party `redis` package from `requirements.txt`, not this project's own `redis_client.py` -- this check deliberately bypasses our code for a minimal, isolated connectivity test.)

Should print `True`.

## 3. GitHub

Push this folder to a repo under your own GitHub account. (Not something
I do from here — see the top of this file.) Steps 4 and 5 both connect to
that repo, so it needs to exist first.

## 4. Render (backend)

1. Sign up at [render.com](https://render.com) (GitHub login is easiest —
   it'll also handle repo access for you).
2. **New** → **Web Service** → connect the GitHub repo from step 3.
3. Runtime: **Docker**. Root directory: `backend/` (so it finds
   `backend/Dockerfile`). Region: same one you picked for Upstash if
   possible.
4. Instance type: the free tier is fine to start. Know its tradeoff:
   it spins down after ~15 minutes idle, so the first request after a
   quiet period is slow (a real cold start, not a bug) — acceptable for a
   v1 launch, worth upgrading later if that's a problem.
5. **Environment** → add every variable from `backend/.env.example`,
   with real values:
   - `GEMINI_API_KEY` — from step 1.
   - `REDIS_URL` — from step 2.
   - `DAILY_USER_CAP`, `GLOBAL_DAILY_CALL_CAP`, `MAX_INPUT_CHARS`,
     `MAX_IMAGE_BYTES`, `MAX_IMAGE_DIMENSION`, `IMAGE_CALL_WEIGHT` — the
     `.env.example` defaults are reasonable starting points.
   - `CORS_ORIGINS` — placeholder for now (e.g. `http://localhost:5500`);
     you'll come back and set this for real in step 6, once step 5 gives
     you the actual frontend URL.
   - `COOKIE_SAMESITE=none`, `COOKIE_SECURE=true` — required once
     frontend and backend are on different domains, which they will be.
   - `ADMIN_TOKEN` — generate one:
     `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
     Save it somewhere (a password manager, not a chat) — you'll need it
     for step 7.
6. **Create Web Service**. Wait for the build/deploy to finish, then note
   the assigned URL (`https://<something>.onrender.com`).
7. Confirm it's alive: `curl https://<your-url>.onrender.com/api/health`
   should return `{"status":"ok"}`.

## 5. Vercel or Netlify (frontend)

Before deploying, edit `frontend/app.js`'s `API_BASE_URL` constant to
your Render URL from step 4, and commit/push that change.

**Vercel**: sign up at [vercel.com](https://vercel.com) → **Add New** →
**Project** → import the same GitHub repo → set **Root Directory** to
`frontend/` → **Deploy** (no build command needed, it's static files).

**Netlify**: sign up at [netlify.com](https://netlify.com) → **Add new
site** → **Import an existing project** → same repo → **Base directory**
`frontend/`, no build command, **Publish directory** `frontend/`.

Either way, note the assigned URL
(`https://<something>.vercel.app` / `.netlify.app`).

## 6. Wire CORS (both directions)

1. Back in Render (step 4)'s environment settings, set `CORS_ORIGINS` to
   the exact frontend URL from step 5 (scheme + host, no trailing slash).
   If you're also using the browser extension, append its
   `chrome-extension://<id>` origin here too, comma-separated.
2. Redeploy the backend (Render redeploys automatically on env var
   changes, or trigger it manually).
3. Open the deployed frontend URL and run a real check end-to-end.

## 7. Production smoke test

Run these against the real deployed URLs, not localhost:

- [ ] `GET /api/health` → `{"status":"ok"}`.
- [ ] Submit a real check via the web UI → verdicts come back, streaming
  visibly (claim cards fill in one at a time).
- [ ] Submit the *exact same* text again → response includes
  `"from_cache": true` and returns near-instantly.
- [ ] In the Upstash dashboard, confirm the command count actually moved
  after that check — this is the proof Redis is really wired in, not
  silently running on the in-memory fallback (which would still *work*,
  just not persist across restarts or multiple instances).
- [ ] Temporarily set `DAILY_USER_CAP=1` on Render, redeploy, submit two
  different checks from the same browser → the second gets a real `429`
  with the friendly message. Restore the real value afterward.
- [ ] Temporarily set `GLOBAL_DAILY_CALL_CAP` to something tiny, redeploy,
  confirm a `503` fires. Restore the real value afterward.
- [ ] `GET /api/admin/stats` with header `X-Admin-Token: <your token from
  step 4>` → 200 with today's usage. Same request with a missing/wrong
  token → 404.
- [ ] If using the browser extension: update
  `extension/results.js`'s `API_BASE_URL` to the Render URL, reload the
  unpacked extension, re-add its (possibly new) id to `CORS_ORIGINS`, and
  re-test both the text and image right-click flows against production.

## 8. (Optional) Publish the extension to the Chrome Web Store

Only if you want it available to regular Chrome users without them
enabling Developer Mode — see `STORE_LISTING.md` for the full checklist
(icons and manifest entries are already done; you still need to host
`PRIVACY.md` at a public URL, write the submission form using
`STORE_LISTING.md`'s draft copy, and create a one-time-$5 Google
Developer account to submit). Do this after steps 4-7 above, since the
listing and `extension/results.js`'s `API_BASE_URL` should point at your
real production backend, not localhost. Expect a multi-day review, and
be ready for the `<all_urls>` host permission to draw questions (see the
permission-justification notes in `STORE_LISTING.md`).

## Ongoing

- Watch Render's log viewer (this app's `logging` output — request/
  response lines, rate-limit rejections) and Upstash's dashboard
  periodically, especially in the first days after launch.
- `GET /api/admin/stats` is the fastest way to check "how close are we to
  today's cap" without digging through logs.
- If real usage patterns suggest the caps are wrong (too tight, too
  loose), they're just env vars on Render — no redeploy of code needed,
  only a settings change + restart.
