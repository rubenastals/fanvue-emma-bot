# Redesign agent + continuous improvement

## Day-to-day (mostly automatic)

Live chats → DeepSeek critic → Soft/Hard board.

**Soft global lessons auto-approve** every ~30 min on the poller (`AUTO_APPROVE_SOFT_LESSONS=1`).
Emma's shared behavior updates without you clicking approve.

**Daily digest** (after 09:00 Los Angeles, once/day): Soft applied + Hard pending + critic errors.
Set one of:

- `DIGEST_WEBHOOK_URL` — Discord or Slack incoming webhook (recommended)
- `DIGEST_EMAIL` + `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM`

Also written to `docs/DAILY_DIGEST.md` and printed in Railway logs.

```bash
# Optional manual refresh / force digest:
python scripts/improve_once.py
python -c "from core import daily_digest; daily_digest.send_digest(force=True)"
```

## Soft vs Hard

| Class | What | Your role |
|---|---|---|
| **Soft** | Global lessons (behavior for all fans) | **None** — auto-approved |
| **Soft personal** | Fan facts/kinks only | Auto on that fan |
| **Hard** | Structure / multi-file | Brief in `docs/briefs/` → you OK merge/deploy |
| **Code autofix** | Cursor tiny edits | Still review `git diff` + deploy |

Turn Soft auto-approve off: `AUTO_APPROVE_SOFT_LESSONS=0`.

## Hard brief chat

Open `docs/briefs/*.md`, paste into Cursor redesign agent, review, then you say merge + deploy.
