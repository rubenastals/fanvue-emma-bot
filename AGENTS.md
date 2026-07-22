# AGENTS.md

## Cursor Cloud specific instructions

Emma is a Python 3.12 Fanvue AI-chatter bot. The **production/primary path** is the
inbox poller (`scripts/poll_inbox.py`); the FastAPI webhook (`api/webhook.py`) is a
**legacy/optional** path. Persistence is Postgres (pgvector) + Redis, with a local
JSON fallback when `DATABASE_URL` is unset.

Python deps live in a virtualenv at `.venv` (created/refreshed by the startup update
script). Activate with `source .venv/bin/activate`.

### Services (must be started each session — not auto-started, no systemd)

Postgres 16 (+pgvector) and Redis are installed system-wide and their data persists in
the VM snapshot, but they are NOT running on boot. Start them before any DB/Redis work:

```bash
sudo pg_ctlcluster 16 main start
sudo service redis-server start
```

DB credentials match `docker-compose.yml`: role `user` / password `password`, database
`fanvue_db`, and the `vector` extension is already created. Standard dev env vars:

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/fanvue_db"
export REDIS_URL="redis://localhost:6379/0"
export ACCOUNT_ID="emma"
```

Initialize/seed the poller schema (idempotent): `python scripts/init_db.py`.

### Lint / test / build / run

- Lint: no linter is configured in this repo (no ruff/flake8/black config).
- Test: `python -m pytest -q`. NOTE: 3 tests in `tests/test_intent_router.py`
  (`test_engacho_spiral`, `test_engacho_pull_mid`, `test_price_objection`) fail on the
  current code and are pre-existing (routing-logic assertions), unrelated to environment
  setup. The rest pass.
- Build: none (interpreted Python). `Dockerfile`/`docker-compose.yml` describe the
  production containers; Docker is not installed in this environment (use the native
  Postgres/Redis above instead).
- Run legacy webhook API: `uvicorn api.webhook:app --host 0.0.0.0 --port 8000`
  (`/health`, `/oauth/status`, `/docs` work without secrets).
- Run production poller: `python scripts/poll_inbox.py --interval 10`.

### Non-obvious gotchas

- The production data layer (`db/pg.py`) forces the psycopg **v3** driver
  (`postgresql+psycopg://`). The legacy `database/db_manager.py` and `create_tables.py`
  use a bare `postgresql://` URL, which SQLAlchemy maps to **psycopg2** — that driver is
  NOT in `requirements.txt`, so the legacy `DBManager` path fails with
  `ModuleNotFoundError: No module named 'psycopg2'`. Prefer the poller/`db/` path.
- The poller boots fully (persona brain, Postgres+Redis, vault sync) but then exits with
  `❌ No Fanvue tokens` until Fanvue OAuth is completed. Live chat replies additionally
  require `DEEPSEEK_API_KEY` (and `XAI_API_KEY` for photo vision). Set these as secrets;
  complete OAuth via `scripts/oauth_login.py` or migrate tokens with
  `scripts/migrate_json_to_pg.py`.
- Embeddings (`utils/embedding_utils.generate_embedding`) are deterministic **mocks**, so
  pgvector-backed reads/writes work with no external embedding API key.
- Prompt/brain architecture rules live in `.cursor/rules/emma-prompt-architecture.mdc` —
  keep the live SIMPLE brain lean; do not stack prompt experiments.
