# Caged Hive Quant

AI-managed quant trading platform under strict survival rules. **Paper trading only.** No fake data.

Architecture follows the research blueprint:
- **Layer 1:** Research & interpretation (Gemini structured JSON, signals)
- **Layer 2:** Deterministic policy & risk engine (non-negotiable)
- **Layer 3:** Execution & observability (Alpaca paper, dashboard, journals)

## Stack

| Layer | Tech |
|-------|------|
| Backend | Python, FastAPI, SQLModel, PostgreSQL |
| Broker | alpaca-py (paper only) |
| AI | Gemini structured JSON output |
| Dashboard | Next.js + Tailwind (reads from API) |
| Deploy | GitHub → Railway |

## Local development

### 1. Backend API

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env   # add secrets
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend dashboard

```bash
npm install
set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:3000

## Environment variables (secrets only)

```env
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ALPACA_BASE_URL=https://paper-api.alpaca.markets
GEMINI_API_KEY=
DATABASE_URL=postgresql://...   # or sqlite:///./hive.db for local
```

Normal config (risk limits, strategy settings, etc.) lives in **database** `config_current` table — not env vars.

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /api/dashboard` | Real dashboard data |
| `POST /api/sync/alpaca` | Sync Alpaca account |
| `GET /api/diagnostic-bundle/download` | Export diagnostic ZIP |
| `POST /api/backtest/run` | Run backtest |
| `POST /api/monte-carlo/run` | Run Monte Carlo (real trades only) |

## Railway deployment (GitHub → Railway)

1. Push to GitHub: `https://github.com/ieshan81/Hive.git`
2. Create Railway project → **Deploy from GitHub repo**
3. Add services (each needs its own **Root Directory** in Railway Settings → Source):
   - **Backend API:** root directory `backend`, builder Nixpacks, env `NIXPACKS_PYTHON_VERSION=3.11`
   - **Frontend:** root directory `/` (repo root), builder Nixpacks
   - **Worker:** root directory `backend`, start command `python worker.py`
   - **Postgres:** add PostgreSQL plugin, set `DATABASE_URL`
4. Set env vars in Railway dashboard
5. Health check: `/health`

If backend build fails with `pip: command not found`, confirm root directory is `backend` and redeploy (or toggle builder Nixpacks ↔ Railpack to bust cache).

**Backend Railway settings (required):**
- Root Directory: `backend`
- Builder: Nixpacks
- Custom Build Command: *(leave empty — Nixpacks reads requirements.txt automatically)*
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Do **not** set `NIXPACKS_INSTALL_CMD` or `NIXPACKS_NO_UPGRADE_PIP` — remove if present; the repo nixpacks.toml no longer runs pip upgrade.

### Frontend on Railway (second service)

- **Root Directory:** `/` (repo root — there is no `frontend/` folder)
- **Builder:** Nixpacks
- **Custom Build Command:** leave empty (repo `nixpacks.toml` uses `npm install`)
- **Start Command:** `npm start` — **NOT** `cd frontend && ...`
- **Variable:** `NEXT_PUBLIC_API_URL` = your backend Railway URL

If build fails on `npm ci` / lock file sync, latest `nixpacks.toml` uses `npm install --include=optional` instead.

## Core modules

- `backend/app/services/alpaca_adapter.py` — real Alpaca paper data
- `backend/app/services/risk_engine.py` — final trade authority
- `backend/app/services/strategy_engine.py` — momentum ORB + pairs mean reversion
- `backend/app/services/quant_math.py` — deterministic formulas
- `backend/app/services/strategy_reviewer.py` — Gemini post-hoc cycle commentary (advisory; disabled in loop by default)
- `backend/app/services/evidence_memory_service.py` — evidence-derived advisory memories
- `backend/app/services/memory_engine.py` — database-backed memory
- `backend/app/services/backtest_engine.py` — real backtests only
- `backend/app/services/monte_carlo_engine.py` — real trade outcomes only
- `backend/app/services/diagnostic_export.py` — full diagnostic bundle

## Empty states (no fake data)

When data is missing, the dashboard shows honest states:
- Not connected
- Waiting for Alpaca sync
- Memory empty
- Backtest not run yet
- Monte Carlo unavailable
- Strategy inactive

## Paper scheduler cron (Railway)

The paper push-pull scheduler is **cron-driven** — enabling `scheduler_enabled` alone does not tick. Configure a Railway **Cron Job** on the backend service:

- **Schedule:** every 10 minutes (`*/10 * * * *`)
- **Command:** `python scripts/cron_paper_scheduler_tick.py`
- **Env:** `OPERATOR_TOKEN`, `HIVE_BACKEND=https://your-backend.up.railway.app`

The script treats `tick_in_progress` and `tick_paced` as success (idempotent, no overlap storms). Overlapping ticks are blocked by a DB lease in `AutonomousPaperScheduler`.

**Preferred prod enable (preserves validation run):**

```
POST /api/autonomous-paper-learning/scheduler/enable
POST /api/autonomous-paper-learning/supervised-burst  {"max_ticks": 2}
```

Do **not** use `start-fresh` unless you have verified it preserves `paper_validation_run_001`.

**Local/dev loop:** `HIVE_PAPER_SCHEDULER_WORKER=1 python worker.py` (separate from Railway web).

## Principles

> Rules trade fast. AI learns slowly. Risk engine blocks danger.

- AI does **not** execute trades
- AI does **not** bypass risk controls
- Live trading is **disabled** in MVP
- No mock trading success
