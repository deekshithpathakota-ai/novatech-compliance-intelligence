# Deploying NovaTech Compliance Intelligence

This guide takes you from the repository to a live demo that judges can open in a browser. No prior Render or Vercel experience is assumed.

---

## Part 1 — Architecture

```text
                    Browser (judges)
                           │
          ┌────────────────┴─────────────────┐
          │ loads the app                     │ API calls (HTTPS, JSON, SSE)
          ▼                                   ▼
   FRONTEND · Vercel                   BACKEND · Render (Docker)
   React + Vite static build           FastAPI + Uvicorn
   VITE_API_URL ───────────────────▶   CORS_ORIGINS allows the Vercel origin
                                              │
                                              ▼
                                   PostgreSQL 16 + pgvector
                                   (Render Postgres / Neon / Supabase)
```

- The **frontend** is a static site. At build time Vite bakes `VITE_API_URL` into the JavaScript, and every API call goes to that address.
- The **backend** is one Docker container. On every boot it applies database migrations, can load the demo data if the database is empty, and then starts the API on the port the host gives it (`$PORT`).
- The **database** needs the `vector` extension. The first migration creates it (`CREATE EXTENSION IF NOT EXISTS vector`).
- OpenAI is **optional**. Without `OPENAI_API_KEY` and `OPENAI_MODEL` the deterministic engine runs every workflow.

---

## Part 2 — Local setup

You need Python 3.11+ (3.12 recommended), Node 20.19+ (22 recommended), and PostgreSQL 16 with pgvector.

### Option A — Docker Compose (everything in one command)

```bash
docker compose up --build
# UI  → http://localhost:5173
# API → http://localhost:8000/api/health
```
Compose starts Postgres + pgvector, the API and the Vite dev server. Demo data is loaded only on the first start, because it only loads into an empty database. Your data survives restarts in the `pgdata` volume.

```bash
docker compose exec api python -m scripts.seed --reset   # fresh demo data
docker compose down -v                                   # delete everything, including the database
```

### Option B — run the pieces yourself

```bash
# 1. Database (Postgres 16 with pgvector installed)
createdb novatech

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                         # add requirements-dev.txt to run the tests
cp .env.example .env                                    # edit DATABASE_URL if needed
python -m scripts.seed                                  # migrations + demo data (~5 s)
uvicorn app.main:app --reload                           # http://localhost:8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                                             # http://localhost:5173
```

Leave `VITE_API_URL` empty for local development. The Vite dev server forwards `/api/*` to `http://localhost:8000`.

Open http://localhost:5173 and click **Continue as Demo User**. Every persona's password is `NovaTech-Demo-2026`.

---

## Part 3 — PostgreSQL setup

Any PostgreSQL 16 with the **pgvector** extension works.

| Provider | Notes |
|---|---|
| **Render Postgres** (easiest; created by `render.yaml`) | pgvector is supported on every plan, including free. Render passes the connection string to the API automatically. Check Render's current limits for free databases (they can expire). |
| **Neon** | Copy the connection string from the dashboard. Keep `?sslmode=require` at the end. |
| **Supabase** | Use the **direct connection** or the **session pooler** URL. Don't use the transaction pooler on port 6543, because it breaks prepared statements. If `CREATE EXTENSION` is refused, enable `vector` under *Database → Extensions*. |

The backend accepts any of these URL formats and converts them to the psycopg 3 driver:

```text
postgres://USER:PASSWORD@HOST:5432/DB
postgresql://USER:PASSWORD@HOST:5432/DB?sslmode=require
postgresql+psycopg://USER:PASSWORD@HOST:5432/DB
```

To check pgvector yourself: `psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extversion FROM pg_extension WHERE extname='vector';"`

---

## Part 4 — Backend deployment (Render)

### Option A — Blueprint (recommended)

1. Push the repository to GitHub.
2. In Render, click **New → Blueprint** and pick the repository. Render reads `render.yaml` and creates:
   - `novatech-api`: a Docker web service built from `backend/Dockerfile`, with health check `/api/health`
   - `novatech-db`: a Postgres database whose URL is passed to the API as `DATABASE_URL`
3. When Render asks for the values marked `sync: false`:
   - `CORS_ORIGINS`: use `http://localhost:5173` for now. You'll replace it with the Vercel URL in Part 5.
   - `OPENAI_API_KEY` / `OPENAI_MODEL`: leave empty unless you want the LLM path.
4. Click **Apply**. The first deploy builds the image (a few minutes), applies the migrations and loads the demo data. Because `SEED_DEMO_DATA=true`, the data is loaded once, only while the database is empty.
5. Copy the service URL, for example `https://novatech-api.onrender.com`, and open `https://novatech-api.onrender.com/api/health/ready`. All checks should show `"ok"`.

### Option B — manual web service

In **New → Web Service**, pick the repository and set:

| Setting | Value |
|---|---|
| Language / Runtime | **Docker** |
| Root Directory | `backend` |
| Dockerfile Path | `./Dockerfile` |
| Health Check Path | `/api/health` |
| Instance type | Free works; paid tiers don't sleep |
| Environment | the variables in Part 6 |

Leave the start command empty. The Dockerfile runs `scripts/start.sh`, which applies the migrations, optionally seeds, and then starts Uvicorn on `0.0.0.0:$PORT`.

> **Free tier sleeps.** After about 15 minutes with no traffic the service sleeps, and the next request takes about 50 seconds while it wakes. The frontend waits up to 70 seconds and shows "backend is starting up" instead of failing. Before a live demo, open `/api/health` a minute early.

---

## Part 5 — Frontend deployment (Vercel)

1. In Vercel, click **Add New… → Project** and import the repository.
2. Configure:

| Setting | Value |
|---|---|
| Root Directory | `frontend` |
| Framework Preset | Vite |
| Build Command | `npm run build` |
| Output Directory | `dist` |
| Install Command | `npm install` |
| Node.js Version | 22.x (Vite 8 needs 20.19+) |
| Environment Variable | `VITE_API_URL` = `https://novatech-api.onrender.com` (your Render URL) |

3. Click **Deploy** and copy the site URL, for example `https://novatech.vercel.app`.
4. **Allow the site in the backend:** in Render, open `novatech-api → Environment`, set `CORS_ORIGINS=https://novatech.vercel.app` and save. Render restarts the service automatically.
5. Open the Vercel URL and click **Continue as Demo User**.

`frontend/vercel.json` rewrites every path to `index.html`, so deep links such as `/findings/3` or `/audits/1/replay` load directly without a 404.

`VITE_API_URL` is inlined at **build** time. If you change it, redeploy the frontend (Deployments → ⋯ → Redeploy).

For Vercel **preview** deployments (a different URL for each branch), also set `CORS_ORIGIN_REGEX=^https://novatech-.*\.vercel\.app$` on Render, adjusted to your project name.

---

## Part 6 — Environment variables

### Backend (Render → Environment, or `backend/.env` locally)

| Variable | Required | Example / default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql://…` | Postgres connection. `postgres://` and `postgresql://` are accepted. |
| `ENVIRONMENT` | ✅ in prod | `production` | Enables the safety checks below. |
| `JWT_SECRET` | ✅ | 32+ random chars | Signs session tokens. In production the API **refuses to start** with a placeholder or short value. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `CORS_ORIGINS` | ✅ | `https://novatech.vercel.app` | Comma-separated frontend origins. No `*` (credentials are used); trailing slashes are ignored. |
| `CORS_ORIGIN_REGEX` | – | `^https://novatech-.*\.vercel\.app$` | Optional: allow Vercel preview URLs. |
| `SEED_DEMO_DATA` | – | `true` | Load demo data at boot **only if the DB is empty**. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | – | – | Optional LLM path; the deterministic engine runs without them. |
| `OPENAI_FAST_MODEL`, `OPENAI_EMBEDDING_MODEL`, `EMBEDDING_PROVIDER` | – | `hash` | Optional model routing. |
| `DISABLE_SCHEDULER` | – | `1` | Turns off the in-process scheduled compliance scan. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_SECONDS` | – | `5`, `5`, `300` | Connection pool tuning. |
| `FORWARDED_ALLOW_IPS` | – | `*` | Trust the host's proxy headers, so rate limits are applied per real client IP. |
| `PORT` | set by host | `8000` | Uvicorn listens on `0.0.0.0:$PORT`. |

### Frontend (Vercel → Settings → Environment Variables)

| Variable | Required | Example |
|---|---|---|
| `VITE_API_URL` | ✅ in production | `https://novatech-api.onrender.com` (a trailing `/` or `/api` is tolerated) |

⚠️ Anything starting with `VITE_` ends up in the public JavaScript bundle. **Never** create `VITE_OPENAI_API_KEY`, `VITE_JWT_SECRET` or anything similar. Secrets belong on the backend only.

---

## Part 7 — Database migrations

The schema is defined by Alembic migrations in `backend/alembic/versions/`: `0001_initial_schema` (tables, the `vector` extension, HNSW and full-text indexes) and `0002_evidence_requests`.

```bash
cd backend
alembic upgrade head        # apply (safe to run repeatedly)
alembic current             # show the applied revision
alembic check               # confirm models and migrations agree (prints "No new upgrade operations detected")
```

In Docker and on Render, `alembic upgrade head` runs automatically on every boot, before the API starts.

---

## Part 8 — Demo data seeding

```bash
python -m scripts.seed                 # migrations, then load demo data ONLY if the database is empty
python -m scripts.seed --reset         # DESTRUCTIVE: drop all app tables, re-migrate, re-seed
python -m scripts.seed --reset --yes   # required when ENVIRONMENT=production
```

- Re-running without `--reset` never touches existing data. It prints *"Demo data already present — nothing to do."*
- The dataset includes 100 employees, 84 controls, 316 evidence items, 57 findings, 9 audits and a second tenant for isolation tests. Dates are relative to the day you seed.
- To give judges a clean slate before a demo, run the reset from Render's **Shell** tab (paid instances), from your machine with the external database URL, or by recreating the database:
  ```bash
  DATABASE_URL="<External Database URL from Render>" ENVIRONMENT=production python -m scripts.seed --reset --yes
  ```

---

## Part 9 — Health checks

| Endpoint | Checks | Use it for |
|---|---|---|
| `GET /api/health` | the process is up (no DB or OpenAI dependency) | Render health check, uptime pings |
| `GET /api/health/ready` | database reachable, pgvector installed, migration applied, demo data present. Returns 503 if not | checking a deployment |

```bash
curl https://novatech-api.onrender.com/api/health
# {"status":"ok","environment":"DEMO","engine":"deterministic"}
curl https://novatech-api.onrender.com/api/health/ready
# {"status":"ok","checks":{"database":"ok","pgvector":"ok","migration":"0002","demo_data":"ok"}}
```

Interactive API docs are at `https://<api>/docs`.

---

## Part 10 — Troubleshooting

The app shows a specific heading and code for each failure. Look them up here:

| What you see | Likely cause | Fix |
|---|---|---|
| **Can't reach the API** — "…CORS_ORIGINS on the backend doesn't include https://…" | The Vercel origin isn't in `CORS_ORIGINS`, or the backend is down | Add the exact origin shown (scheme + host, no path) to `CORS_ORIGINS` on Render, then check `/api/health`. |
| **API URL is misconfigured** / "received a web page instead of API data" / "rejected the request method" | `VITE_API_URL` is missing or points at the Vercel site | Set `VITE_API_URL` to the Render URL and **redeploy** the frontend. |
| **Backend unavailable** — "starting up" (HTTP 502/503/504) | Render free instance waking up, or a deploy in progress | Wait 30–60 s and retry. |
| **The API took too long to respond** | Cold start took over 70 s, or the network is slow | Retry. Warm the service by opening `/api/health` first. |
| **Database unavailable** (`SERVICE_UNAVAILABLE`) | The database is down or `DATABASE_URL` is wrong | Check `/api/health/ready` and the Render DB status. The API reconnects automatically. |
| **Session expired** | Token expired (8 h) or signed out elsewhere | Sign in again. |
| Render deploy log: `Unsafe configuration: JWT_SECRET …` | Placeholder or short secret with `ENVIRONMENT=production` | Set a 32+ character `JWT_SECRET`. |
| Render deploy log: `Unsafe configuration: CORS_ORIGINS is empty` | `CORS_ORIGINS` not set | Set it to your Vercel URL. |
| Deploy log: `could not translate host name` / `connection refused` | Wrong `DATABASE_URL` | Use the database's **Internal** URL on Render (or the provider's URL with `sslmode=require`). |
| Deploy log: `permission denied to create extension "vector"` | Provider needs pgvector enabled | Enable the `vector` extension in the provider dashboard, then redeploy. |
| `/api/health/ready` shows `"demo_data":"empty"` | The database has no data yet | Set `SEED_DEMO_DATA=true` and redeploy, or run `python -m scripts.seed`. |
| Vercel 404 on refresh of a deep link | Root Directory isn't `frontend`, so `vercel.json` isn't used | Set Root Directory = `frontend`. |
| Uploaded documents disappear after a redeploy | Render's disk is ephemeral | Expected in the prototype. Extracted text and chunks live in Postgres; only the raw upload file is lost. |
| Browser console: font requests blocked | Network blocks Google Fonts | Cosmetic only; system fonts are used instead. |
