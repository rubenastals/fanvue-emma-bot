# Redesign agent + continuous improvement

## What you actually do day-to-day (minimal)

Live chats already feed the DeepSeek critic. You do **not** read conversations one by one.

```bash
# Once a day (or when logs say "improve board"):
python scripts/improve_once.py --all
```

That command:

1. Aggregates critic errors + pending lessons + autofix queue from **live** chats  
2. Asks DeepSeek for **Soft** vs **Hard** proposals  
3. Writes `docs/IMPROVE_BOARD.md` (human-readable)  
4. **Soft:** auto-approves pending lessons + runs Cursor autofix (tiny code/prompt fixes)  
5. **Hard:** writes filled briefs under `docs/briefs/`  

Your only manual steps:

- Soft code changes: glance `git diff` → push / `railway up` when happy  
- Hard: open a brief file → paste into Cursor → review → you say merge + deploy  

The poller also refreshes the board every ~30 min and prints Soft/Hard counts in Railway logs.

---

## Soft vs Hard

| Class | Examples | How it ships |
|---|---|---|
| **Soft** | Lessons, lorebook JSON, tiny `turn_policy` / prompt tweaks via autofix | `improve_once.py --apply-soft` then you deploy |
| **Hard** | New modules, schema, memory architecture, deploy behavior | Auto brief → redesign agent → **your** OK |

---

## Template for a Hard brief chat (usually auto-written)

If you open `docs/briefs/*.md`, it is already filled. Paste the file contents into Cursor.

Manual template (only if you invent a Hard change yourself):

```markdown
### 1. Problema medible
…

### 2. Por qué auto-fix no basta
…

### 3. Diseño propuesto
- Soft or Hard: Hard
- Files / flow:

### 4. Qué NO cambia
OAuth, tokens, .env, vault prices, secrets.

### 5. Criterio de éxito + verificación
…

### 6. Rollback
…
```

Agent constraints:

```
You are the Emma Fanvue redesign agent. Follow docs/REDESIGN_BRIEF.md.
Soft first. One thesis. Branch only. NEVER push main / railway up unless human asks.
```

---

## Deploy checklist (Hard / Soft code)

1. Review `git diff`  
2. Push / `railway up --service poller`  
3. Poller drains on SIGTERM (finishes current turn, releases Redis lock)  
4. Logs: `redis lock: acquired` then `.` / `handled`  

Honest limit: a few seconds gap on redeploy. DMs are not live sockets.
