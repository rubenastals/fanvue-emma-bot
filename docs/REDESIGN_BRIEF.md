# Redesign agent + safe deploys

Two tracks. Do not mix them.

| | Auto-fix (exists) | Redesign agent (this brief) |
|---|---|---|
| Trigger | Critic rule repeats | You paste a filled brief |
| Scope | Minimal diff in policy/prompt | Structure / serious features |
| Autonomy | `--run` supervised | **Never** to `main` without your OK |
| Production | After review + deploy | After review + **drain deploy** |

Auto-fix template: [`core/auto_fix.py`](../core/auto_fix.py) (`FIX_PROMPT_TEMPLATE`) — still forbids refactors.  
Redesign system prompt: [`scripts/redesign_agent.md`](../scripts/redesign_agent.md).

---

## Soft vs Hard (redeploy or not)

| Class | What | Redeploy? |
|---|---|---|
| **Soft** | Global/fan lessons, client card, memory, `lorebook.json` | Usually **no** — lorebook hot-reloads ~5 min |
| **Hard** | `turn_policy`, `reply_engine`, extractors, schema, OAuth, packs wired in code | **Yes** — use drain deploy |

Soft global auto-approve: `AUTO_APPROVE_SOFT_LESSONS` (default **0** — Soft stays pending; does not flood live prompt).  
Live Soft inject: `INJECT_LESSONS=0` (keep off).

Hourly last-hour review: `HOUR_REVIEW_ENABLED=1` → Soft/Hard proposals only (no live inject).

---

## Brief template (fill BEFORE touching code)

Copy this block into chat with the redesign agent. Empty sections → agent must refuse to code.

```markdown
## 1. Problema medible
(What fails in production? Quote logs / fan lines. Not “mejorar Emma”.)

## 2. Por qué el auto-fix no basta
(Why a tiny policy/prompt patch is not enough.)

## 3. Diseño propuesto
(Files, data, flow. One thesis.)

## 4. Qué NO cambia
(Default: OAuth, vault prices/catalog UUIDs, tokens, schema without migration.)

## 5. Criterio de éxito + verificación
(How we know it worked: log lines, fan test, smoke command.)

## 6. Clase de cambio
Soft | Hard

## 7. Plan de rollback
(Revert commit / env var / redeploy previous.)
```

### Hard rules (agent must obey)

1. Changes that “improve” without evidence of failure → **reject**.
2. One thesis per PR; no drive-by refactors.
3. Soft first if it solves the problem.
4. Hard only with backward-compatible migration (read old + write new).
5. After edits: `python -c "import scripts.poll_inbox"` + deploy checklist below.
6. Never auto-merge to `main` or auto-deploy to Railway.

---

## Operator flow

1. Fill the brief template (evidence required).
2. Open Cursor with [`scripts/redesign_agent.md`](../scripts/redesign_agent.md) as system / paste brief.
3. Agent implements on a **feature branch**.
4. You review `git diff` → merge when OK.
5. Deploy Hard changes with drain (Railway `railway up --service poller`).
6. Watch logs 1–2 minutes.

Daily Soft/Hard board (optional):

```bash
python scripts/improve_once.py
python -c "from core import daily_digest; daily_digest.send_digest(force=True)"
```

Digest: `DIGEST_WEBHOOK_URL` or `DIGEST_EMAIL` + SMTP_*. Also `docs/DAILY_DIGEST.md` / Railway logs.

Hard briefs from improve board: `docs/briefs/*.md` — paste into redesign agent, then merge + deploy yourself.

---

## Deploy checklist (Hard)

Poller drains on SIGTERM/SIGINT: finishes the **current fan turn** (bubbles + attach), does **not** start new chats, **releases Redis lock**, exits 0. New container acquires lock in seconds.

- [ ] Not mid OAuth / token experiment
- [ ] Soft-only? Prefer lorebook / lessons — skip redeploy if possible
- [ ] `railway up --service poller` (or GitHub → Railway)
- [ ] Logs 1–2 min: `.` / `handled` / `redis lock: acquired` / no crash loop
- [ ] If boot fails: Railway `ON_FAILURE` retries ([`railway.toml`](../railway.toml))

Honest gap: a few seconds while the new container starts. Pending DMs process on return; there is no long-lived socket session to lose.

---

## Lorebook hot-reload (Soft without kill)

Edit [`core/lorebook.json`](../core/lorebook.json). Poller reloads from disk about every **5 minutes** (`ensure_fresh`). No redesign PR required for keyword style ammo.
