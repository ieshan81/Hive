# Caged Hive FinBERT Service

Optional Railway microservice for financial text sentiment.

- **RAM:** ~1.5–2.5 GB with ProsusAI/finbert on CPU
- **Env:** `FINBERT_MODEL`, `FINBERT_DISABLE=1` to run health-only without loading weights
- **Endpoints:** `/health`, `/model/status`, `/sentiment/classify`, `/sentiment/batch`

Main Hive backend sets `FINBERT_SERVICE_URL` and uses `backend/app/services/finbert_client.py`.
