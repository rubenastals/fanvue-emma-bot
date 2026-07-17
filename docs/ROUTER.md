# Emma router — boolean gates + situation packs

## Principle

```
Hard truth = CODE (API / memory / cooloffs)
Soft intent = regex (optional JSON if SOFT_CLASSIFY=1)
Creativity  = DeepSeek final reply only
One turn    = CORE + CARD + HISTORY + 1 PACK
```

Never dump Soft lessons or fat essays into the live prompt.

## Pipeline

1. **HardGates** — unpaid PPV, free_in_chat, fan media, chill/reject windows  
2. **SoftClassify** — regex booleans; if ambiguous and `SOFT_CLASSIFY=1`, cheap JSON call  
3. **PickWinningPack** — first match in `packs/_index.json` priority  
4. **Assemble** — budgets in `core/prompt_layers.py`  
5. **Creative reply** — DeepSeek writes 1–3 lines  
6. **Sanitize + API verify** — free/PPV attach + timed unsend

## Sales phases (your big playbook → packs)

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

The 10 absolute laws live in `core/prompt_core.py`. Tactics live only in the winning pack — never paste the full essay into the system prompt.

## Manipulation engine (loudest layer)

When the pack is manipulative, the prompt injects a banner **before** the pack:

```
MANIPULATION ENGINE — #1 PRIORITY NOW
ACTIVE TECHNIQUE >>> GUILT TRIP + RECIPROCITY <<<
```

Picker: `core/manipulation.py` (one technique per turn; rotates on pull; steps 1–4 on objection).
Author note also nudges: `execute manipulation technique […]`.

See [`TECHNIQUES.md`](TECHNIQUES.md).

## Turn order (important)

1. **Code hard gates** (PPV unpaid, delivery API, chill…)  
2. **Phase analyst** (DeepSeek): reads full chat + CLIENT CARD → phase, pack, name, likes  
3. **CLIENT RECALL** block injected  
4. **Manipulation ENGINE** (one technique)  
5. **Situation pack**  
6. **Creative DeepSeek** writes the reply  

Env: `PHASE_ANALYST=1` (default). Set `0` to skip the analyst call.

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
- After DeepSeek rewrite, manually fix conflicts (e.g. close must still fire lock same turn)

## Adding a casuistry

1. Create `packs/my_case.md` with MUST / SHOULD / NEVER (keep under ~1200 chars).  
2. Insert `my_case` into `_index.json` priority at the right height.  
3. Add a hard or soft flag in `core/intent_router.py` (`_hard_route` or `_soft_active`).  
4. Add a row to `tests/test_intent_router.py`.  
5. Do **not** grow `prompt_core.py` unless it is a universal hard ban.

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
| `LEAN_CREATIVE` | `1` | Short CORE + packs path |
| `INJECT_LESSONS` | `0` | Soft never in live |
| `SOFT_CLASSIFY` | `0` | Extra JSON classify when ambiguous |
| `SOFT_CLASSIFY_MODEL` | (main model) | Optional cheaper model |
| `PPV_EXPIRE_MINUTES` | `30` | Timed unpaid lock unsend |

## Code map

| Module | Role |
|--------|------|
| `core/turn_facts.py` | Boolean facts dataclass |
| `core/intent_router.py` | Hard → soft → pack_id + TurnDecision |
| `core/soft_classify.py` | Optional JSON classifier |
| `core/packs.py` | Load/render one pack |
| `packs/*.md` | Situation rules |
| `core/reply_engine.py` | Injects winning pack into prompt |
| `scripts/poll_inbox.py` | Routes each fan turn |

## Logs

Each turn prints:

```
pack: lock_now | mode=soft_sell | price=True | via=regex
prompt: CORE=… CARD=… TURN=… pack=lock_now
```
