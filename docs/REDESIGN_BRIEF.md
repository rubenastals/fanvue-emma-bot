# Redesign agent brief

Use this when a change is **too big for auto-fix** (structure, new modules, memory model, deploy safety). Fill every section **before** editing code. One thesis per PR. Never merge to `main` or redeploy without human approval.

Auto-fix (`scripts/auto_fix.py`) stays for tiny steering diffs only. This brief is for serious redesigns.

---

## Template (copy into the agent chat)

```markdown
### 1. Problema medible
(What fails in real chats / ops? Quote examples. Not "improve Emma".)

### 2. Por qué auto-fix no basta
(Needs new module / schema / deploy behavior / multi-file design.)

### 3. Diseño propuesto
- Files to touch:
- Data / flow change:
- Soft or Hard: Soft | Hard

### 4. Qué NO cambia
(Default: OAuth, vault prices, tokens, secrets, unrelated refactors.)

### 5. Criterio de éxito + verificación
- Success looks like:
- Verify with: `python -c "import scripts.poll_inbox"` + …

### 6. Rollback
(Revert commit / feature flag / restore previous Railway deploy.)
```

---

## Soft vs Hard

| Class | Examples | Production |
|---|---|---|
| **Soft** | Lessons approve, client-card facts, lorebook JSON tweaks | Prefer **no** process kill. Lorebook hot-reloads from disk ~every 5 min. Lessons/memory already load from Postgres per turn. |
| **Hard** | `turn_policy`, `reply_engine`, extractors, schema, OAuth, poller loop | Needs redeploy. Poller **drains**: finishes current fan turn, releases Redis lock, then exits so the new replica can start in seconds. |

Rules:

- Prefer Soft if it solves the problem.
- Hard changes must stay backward-compatible (read old JSON keys; migrate write-path carefully).
- No drive-by refactors. No new dependencies unless the brief says so.
- Reject “improvements” with no measurable failure.

---

## Agent constraints (paste with the filled template)

```
You are the Emma Fanvue redesign agent.
1. Fill / respect the brief above. If a section is empty, stop and ask.
2. Soft first. Hard only if Soft cannot fix it.
3. Minimal coherent diff. One thesis. No unrelated cleanup.
4. NEVER touch: .env, .fanvue_tokens.json, vault prices, secrets.
5. NEVER push to main or run railway up unless the human explicitly asks.
6. After edits: python -c "import scripts.poll_inbox"
7. End with: root cause, files changed, Soft/Hard, how to verify, rollback.
```

---

## Deploy checklist (Hard changes)

1. Review `git diff`. Merge only with human OK.
2. Do **not** deploy mid-OAuth experiment.
3. `railway up --service poller` (or your usual push/deploy).
4. Old poller gets SIGTERM → finishes current turn → releases Redis lock → exits.
5. Watch logs 1–2 min: `redis lock: acquired`, then `.` / `--- handled`.
6. If boot fails, Railway `ON_FAILURE` retries (`railway.toml`).

Honest limit: a few seconds of gap while the new container starts. Fanvue DMs are not live sockets; pending messages are picked up after restart. `processed` is marked before send to avoid double-replies.
