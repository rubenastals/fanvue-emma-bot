# Deploy Emma poller on Railway (Postgres + Redis)

This is the production path for `scripts/poll_inbox.py`.  
Cursor auto-fix stays on your PC — do **not** run it on Railway.

## Architecture

| Piece | Role |
|--------|------|
| **poller** service | Long-running inbox loop (Dockerfile CMD) |
| **Postgres** | accounts, oauth tokens, fan_memory, lessons, vault, conversation_events |
| **Redis** | processed message UUIDs + single-poller lock |
| **ACCOUNT_ID** | `emma` today; add rows later for more creators |

Local JSON files are still used when `DATABASE_URL` is unset (dev without Docker).  
Keep `DATABASE_URL` / `REDIS_URL` **commented in `.env`** until Postgres/Redis are actually running, or the local poller will fail to connect.

## 1. Local smoke (Docker Compose)

```bash
cd fanvue-emma-bot
# ensure .env has DEEPSEEK_*, FANVUE_*, XAI_* (and existing OAuth tokens file)

docker compose up -d postgres redis
docker compose run --rm init-db

# Load current Emma state into PG/Redis
set DATABASE_URL=postgresql://user:password@localhost:5432/fanvue_db
set REDIS_URL=redis://localhost:6379/0
set ACCOUNT_ID=emma
python scripts/migrate_json_to_pg.py

docker compose up -d poller
docker compose logs -f poller
```

Stop the Windows `poll_inbox.py` process before starting the container, or Redis lock will idle one of them (`z` in logs).

## 2. Railway project

1. Create a Railway project from this repo (`fanvue-emma-bot`).
2. Add plugins: **PostgreSQL** + **Redis**.
3. One service from Dockerfile (poller). Start command (if override needed):

   `python scripts/poll_inbox.py --interval 10`

4. Set variables (same secrets as local `.env`):

| Variable | Notes |
|----------|--------|
| `DATABASE_URL` | From Railway Postgres (auto) |
| `REDIS_URL` | From Railway Redis (auto) |
| `ACCOUNT_ID` | `emma` |
| `DEEPSEEK_API_KEY` | required |
| `DEEPSEEK_MODEL` | e.g. `deepseek-v4-pro` |
| `DEEPSEEK_DISABLE_THINKING` | `1` |
| `FANVUE_CLIENT_ID` | required |
| `FANVUE_CLIENT_SECRET` | required |
| `FANVUE_API_VERSION` | `2025-06-26` |
| `XAI_API_KEY` | Grok vision for fan photos |
| `XAI_VISION_MODEL` | `grok-4.3` |

Optional: `FANVUE_MEDIA_MAP` only if you mount a map file; after migrate, vault lives in Postgres.

5. **Seed data once** (from your PC against Railway URLs):

```bash
set DATABASE_URL=<railway postgres url>
set REDIS_URL=<railway redis url>
set ACCOUNT_ID=emma
python scripts/init_db.py
python scripts/migrate_json_to_pg.py
```

Or run a one-off Railway shell with the same commands after copying token/memory JSON into the job.

6. Deploy. Confirm logs show:

```text
storage: Postgres + Redis (account=emma)
🔥 Emma polling @im.emmacarter ...
```

## 3. OAuth / tokens

- Easiest: migrate `.fanvue_tokens.json` with `migrate_json_to_pg.py` (above).
- Refresh continues in-process via Fanvue refresh_token stored in `oauth_tokens`.
- Re-login later: run local OAuth, then re-migrate tokens only (or PATCH `oauth_tokens`).

## 4. Scaling later (dozens of accounts)

- Insert another row in `accounts` + its `oauth_tokens` / `vault_media`.
- Run **N poller replicas** with different `ACCOUNT_ID`, **or** one worker that loops accounts (future).
- Keep DeepSeek / xAI keys global (your APIs).
- Never run Cursor auto-fix inside Railway.

## 5. Checklist

- [ ] Postgres + Redis attached  
- [ ] Env vars set  
- [ ] `init_db` + `migrate_json_to_pg` done for Emma  
- [ ] Local poller stopped  
- [ ] Railway poller logs healthy  
- [ ] Send a test DM + a photo (Grok vision)  
