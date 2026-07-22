# Auditoría Emma — tablero de cierre

Principle: **protocol = code**. DeepSeek only writes text for an ACTION the poller already chose. No more prompt essays to fix loops.

## Done

| # | Item | Status |
|---|------|--------|
| A1 | One live brain (SIMPLE canonical) + docs/rules aligned | ✅ |
| A2 | Soft lessons out of live (`INJECT_LESSONS=0`) | ✅ |
| A3 | Persona priority ladder + TECHNIQUE conditional | ✅ |
| A4 | Safe fallbacks (no Mmm… openers) + regression matrix | ✅ |
| A5 | Complete bubbles (no mid-sentence chops) | ✅ |
| A6 | THREAD BEAT = last real turns (not stale summary) | ✅ |
| A7 | `open_commitment` + action-first voice (v1) | ✅ |
| A8 | Hard-block PPV while voice debt open | ✅ |
| **R1** | **Dumb voice FSM** — open_voice → SEND (no rolls/packs/horny) | ✅ |
| **R2** | **Cap rewrite cascade** — `MAX_CREATIVE_REWRITES=1`; hard lies → strip/fallback only | ✅ |
| **R3** | **Quarantine dead brains** — banners + `core/quarantine.py` + autofix/docs | ✅ |
| **R5** | **TurnAction resolver** — voice > comfort > attach_ppv/free > flirt before LLM | ✅ |
| **R6** | **Expanded audit matrix** — cross-seam tests + one-command runner | ✅ |
| **R4** | **Split `reply_engine`** — assemble / generate / sanitize seams | ✅ |

## Remaining (finish BEFORE polish)

_(none — audit board complete.)_

## Ship

- Tag / release: `good-20260722-1132-audit-r1-r6-r4-complete-on-main`
- GitHub release: https://github.com/rubenastals/fanvue-emma-bot/releases/tag/good-20260722-1132-audit-r1-r6-r4-complete-on-main
- Deploy: `railway up --service poller -y` from `main` (needs `RAILWAY_TOKEN` or CLI login)

## Explicitly NOT doing now

- More CRITICAL banners in TURN
- Growing `emma.md`
- Soft lesson injection
- Blind history window bumps as a “memory fix”

## Order of work

1. R1 (voice WHEN) ✅  
2. R2 (rewrite cap) ✅  
3. R3 (quarantine) ✅  
4. R5 lite (action resolver) ✅  
5. R6 tests ✅  
6. R4 split ✅  

## R4 notes

- `core/reply_assemble.py` — `assemble_emma_turn` → `AssembledTurn`
- `core/reply_sanitize.py` — `apply_post_draft` + rewrite budget / strips / bubbles
- `core/reply_engine.py` — thin facade: assemble → `_call_creative` → sanitize
- Public imports from `reply_engine` unchanged (poller / tests)
- Runner: `python scripts/run_audit_matrix.py`
