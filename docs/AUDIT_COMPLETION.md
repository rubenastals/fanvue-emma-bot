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
| A7 | `open_commitment` + action-first voice (v1) | ✅ partial — **trigger still too clever** |
| A8 | Hard-block PPV while voice debt open | ✅ |

## Remaining (finish BEFORE polish)

| # | Item | Why it matters |
|---|------|----------------|
| **R1** | **Dumb voice FSM** — open_voice → SEND on next non-reject fan msg. No rolls/packs/horny on committed path. | “When to send” was soup — **in progress this PR** |
| **R2** | Cap rewrite cascade — 1 creative call; only deterministic strips for hard lies | Rewrites wipe good replies / context |
| **R3** | Quarantine dead brains (`reply_v2`, fat `system_prompt`, unused STRATEGY essay) | Agents patch the wrong surface |
| **R4** | Split `reply_engine` seams: assemble / generate / sanitize | God-object = every fix breaks another |
| **R5** | Generalize `TurnAction` (flirt / send_voice / attach_ppv / comfort) — one resolver before LLM | Same class of bugs as voice/PPV |
| **R6** | Expand matrix tests: voice FSM, no-PPV-with-debt, unpaid, bluff, ES | Prevent regression while refactoring |

## Explicitly NOT doing now

- More CRITICAL banners in TURN
- Growing `emma.md`
- Soft lesson injection
- Blind history window bumps as a “memory fix”

## Order of work

1. R1 (voice WHEN)  
2. R2 (rewrite cap)  
3. R3 (quarantine)  
4. R5 lite (action resolver skeleton)  
5. R6 tests  
6. R4 split (larger; after R1–R3 stable)
