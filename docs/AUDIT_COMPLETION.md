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

## Remaining (finish BEFORE polish)

| # | Item | Why it matters |
|---|------|----------------|
| **R4** | Split `reply_engine` seams: assemble / generate / sanitize | God-object = every fix breaks another |

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
6. R4 split (larger; last)

## R2 notes

- Config: `MAX_CREATIVE_REWRITES` (default `1`) — spent on lang / length / complete / grammar only.
- Hard lies never call DeepSeek again: delivery, sell sync, wait timing, purchase bluff, invented lock/video, ghost stall, blame, wrong `$`, continuity question strip.
- Helpers: `RewriteBudget`, `_fix_invented_wait_minutes`; tests in `tests/test_rewrite_budget.py`.

## R3 notes

- Registry: `core/quarantine.py` (`QUARANTINE_MARKER` on each dead surface).
- `poll_inbox` lazy-imports `reply_v2` only when `REPLY_V2 and not SIMPLE`.
- Autofix / TECHNIQUES / ROUTER / cursor rule point at `personas/emma.md` + code gates.
- Tests: `tests/test_quarantine_dead_brains.py`.
- Emergency paths (`SIMPLE=0`, `REPLY_V2=1`+`SIMPLE=0`, `LEAN=0`) kept importable.

## R5 notes

- `core/turn_action.py`: `plan_turn_action` / `classify_turn_action` / `action_prompt_line`
- Priority: `send_voice` > `comfort` > `attach_ppv` > `attach_free` > `flirt`
- `poll_inbox` logs `ACTION=…` from one resolver; `generate_emma_reply(turn_action=…)`
- Tests: `tests/test_turn_action.py`

## R6 notes

- Runner: `python scripts/run_audit_matrix.py`
- Matrix: `tests/test_regression_matrix.py` (+ suite modules listed in the runner)
- Guards against Copilot-style anti-fixes: no blind history bumps, no fat-prompt lever, no multi-LLM rewrite cascade
