# Emma router — boolean gates + situation packs

## Live brain (canonical)

Defaults in `config.py`:

```
SIMPLE_PROMPT=1   ← creative path (personas/emma.md + TURN facts)
LEAN_CREATIVE=1
INJECT_LESSONS=0
PHASE_ANALYST=0
SOFT_CLASSIFY=0
REPLY_V2=0
```

```
Hard truth = CODE (API / memory / cooloffs / attach / commitments)
Soft intent = regex (optional JSON if SOFT_CLASSIFY=1)
Creativity  = DeepSeek final reply only (never owns protocol)
SIMPLE turn = CORE(persona) + CARD + HISTORY + TURN facts + AUTHOR

**Action-first (R5):** `plan_turn_action` in `core/turn_action.py` chooses ONE
ACTION before DeepSeek: `send_voice` > `comfort` > `attach_ppv` > `attach_free`
> `flirt`. Voice uses `open_commitment` in fan_memory. Prompt gets a short
ACTION / COMMITMENT line — protocol is code, not Soft memory.
```

When `SIMPLE_PROMPT=1` (production default):

- Router still picks **one** `pack_id` for hard gates, sell flags, and logs.
- Pack markdown (`packs/*.md`) is **not** injected into the prompt.
- Tactics live in `personas/emma.md`; per-turn truth in LOCK/SELL/DELIVERY/AUDIO/TRUTH STATE.

When `SIMPLE_PROMPT=0` (legacy): CORE short + manipulation banner + one pack (see below). Do not grow that path.

Never dump Soft lessons or fat essays into the live prompt.

## How we know DeepSeek follows the scheme

| Layer | What | When |
|-------|------|------|
| **Hard gates** | Code chooses pack, blocks 2nd PPV, attaches media, unsends locks | every turn |
| **Loud prompt** | LOCK / SELL STATUS + persona (SIMPLE) or MANIP + 1 pack (legacy) | every turn |
| **scheme_guard** | Deterministic check after reply (invented candado, bluff, sell sync) | every turn → logs `⚠ scheme_fail` |
| **Critic SCHEME** | DeepSeek scores pack/lock/technique obedience | async after turn |
| **scheme_check** | Offline report of packs/techs/guard hits | `python scripts/scheme_check.py [--critic]` |

DeepSeek is creative Soft — it can still drift. Hard gates + guard catch the expensive lies; critic/board catch soft drift for pack enrichment (offline / legacy).

## Pipeline

1. **HardGates** — unpaid PPV, free_in_chat, fan media, chill/reject windows  
2. **SoftClassify** — regex booleans; if ambiguous and `SOFT_CLASSIFY=1`, cheap JSON call  
3. **PickWinningPack** — first match in `packs/_index.json` priority  
4. **Offer select** — whether to attach; unpaid never stacks a second lock  
5. **Assemble** — budgets in `core/prompt_layers.py` (SIMPLE: persona + TURN facts)  
6. **Creative reply** — DeepSeek writes 1–2 short lines  
7. **Sanitize + scheme_guard + API verify** — rewrite belts, free/PPV attach + timed unsend  

## Sales phases (pack ids — gates / logs; creative only if SIMPLE=0)

| Phase | Pack | When |
|-------|------|------|
| Hook (first msgs) | `phase_hook` | msgs &lt; 4, new |
| Spiral | `phase_spiral` | warming / sensory |
| Pull | `phase_pull` | manipulation / desire |
| Close | `phase_close` | fire paid lock |
| Price objection | `price_objection` | after reject |
| Reward | `reward_purchase` | &lt;15m after buy |
| Withdrawal | `post_sale_withdrawal` | after reward window |
| Re-engage | `phase_reengage` | silence nudges |

Hard bans / persona laws live in `personas/emma.md` (SIMPLE) or `core/prompt_core.py` (legacy).

## Legacy only (`SIMPLE_PROMPT=0`): manipulation engine

When the pack is manipulative, the prompt injects a banner **before** the pack:

```
MANIPULATION ENGINE — #1 PRIORITY NOW
ACTIVE TECHNIQUE >>> GUILT TRIP + RECIPROCITY <<<
```

Picker: `core/manipulation.py`. See [`TECHNIQUES.md`](TECHNIQUES.md).

Phase analyst (`PHASE_ANALYST`) defaults **off**. Only used on the non-SIMPLE path.

## Priority (high → low)

See [`packs/_index.json`](../packs/_index.json). Hard delivery/PPV gates still beat sales phases.

## Enrich packs (DeepSeek + history — offline)

```bash
python scripts/enrich_packs.py              # rewrite packs from critic/lessons
python scripts/enrich_packs.py --only phase_hook billing_clarify
python scripts/enrich_packs.py --no-deepseek  # anti-regression fallback only
```

Rules for enrichment (do **not** regress):

- One pack / turn still; `budget_chars` ≈ 1400 in `_index.json`
- Bake past failures into NEVER (fake delivery, invent names, glitches, Soft dumps)
- Never paste Soft lessons into live prompt (`INJECT_LESSONS=0`)
- Under SIMPLE, pack edits do **not** change live creative text — use for gates/offline only unless you switch `SIMPLE_PROMPT=0`

## Adding a casuistry

**Prefer (SIMPLE live):**

1. Code hard gate in `intent_router` / `poll_inbox` / `scheme_guard`, **or**
2. Replace one rule in `personas/emma.md` (do not append forever), **or**
3. A small TURN fact block only if code cannot express it.

**Legacy pack path (`SIMPLE=0`):**

1. Create `packs/my_case.md` with MUST / SHOULD / NEVER (keep under ~1200 chars).  
2. Insert `my_case` into `_index.json` priority.  
3. Add a hard or soft flag in `core/intent_router.py`.  
4. Add a row to `tests/test_intent_router.py`.  

## Pack format

```markdown
# pack_id
MUST:
- firm rules this turn
SHOULD:
- soft guidance
NEVER:
- hard bans for this situation
```

## Config

| Env | Default | Meaning |
|-----|---------|---------|
| `SIMPLE_PROMPT` | `1` | Persona + TURN facts (canonical live) |
| `LEAN_CREATIVE` | `1` | Layered budgets |
| `INJECT_LESSONS` | `0` | Soft never in live |
| `SOFT_CLASSIFY` | `0` | Extra JSON classify when ambiguous |
| `SOFT_CLASSIFY_MODEL` | (main model) | Optional cheaper model |
| `PHASE_ANALYST` | `0` | Legacy analyst call (off) |
| `REPLY_V2` | `0` | Parallel brain (off; ignored when SIMPLE=1) |
| `PPV_EXPIRE_ENABLED` | `1` | Unsend unpaid locks on a timer |
| `PPV_EXPIRE_MINUTES` | `30` | Timed unpaid lock unsend |
| `PPV_PURGE_ACTIVE_ON_START` | `1` | Wipe ALL unpaid locks when poller boots |

Emma sees a loud **LOCK STATUS** every turn (active + ~minutes left, or none). Persist on the waiting candado; never invent one when none.

## Code map

| Module | Role |
|--------|------|
| `personas/emma.md` | SIMPLE live CORE |
| `core/prompt_core.py` | Persona loader + legacy CORE |
| `core/prompt_layers.py` | Budgets / layer assemble |
| `core/turn_facts.py` | Boolean facts dataclass |
| `core/intent_router.py` | Hard → soft → pack_id + TurnDecision |
| `core/soft_classify.py` | Optional JSON classifier |
| `core/packs.py` | Load/render one pack (legacy inject) |
| `packs/*.md` | Situation rules (gates/logs under SIMPLE) |
| `core/reply_engine.py` | Facade: assemble → draft → sanitize |
| `core/reply_assemble.py` | Prompt / HISTORY / TURN facts (R4) |
| `core/reply_sanitize.py` | Post-draft belts / bubbles (R4) |
| `core/scheme_guard.py` | Post-reply hard checks + safe fallbacks |
| `scripts/poll_inbox.py` | Routes each fan turn |
| `core/quarantine.py` | Dead-brain registry (audit R3) |

## DO NOT EDIT for live SIMPLE fixes (quarantined)

| Module | Why dead under production defaults |
|--------|-------------------------------------|
| `core/reply_v2.py` / `core/emma_prompt_v2.py` | Ignored when `SIMPLE_PROMPT=1` |
| `core/system_prompt.py` | Fat essay; only if `LEAN_CREATIVE=0` |
| `STRATEGY_BLOCK` in `core/strategy_prompt.py` | Offline; live uses `truth_state()` |
| `core/manipulation.py` | Technique banners only if `SIMPLE=0` |
| `core/phase_analyst.py` | Off unless `PHASE_ANALYST` + non-SIMPLE |
| `core/strategy_orchestrator.py` | Celery legacy — not `poll_inbox` |

Emergency flags keep these importable; see banners at top of each file.

## Logs

Each turn prints:

```
pack: lock_now | mode=soft_sell | price=True | via=regex
prompt: v=… CORE=… CARD=… TURN=… pack=lock_now SIMPLE
```
