# Técnicas → Fases (Emma)

Full taxonomy (families, mechanisms, FORBIDDEN):
[`DARK_PSYCH_TAXONOMY.md`](DARK_PSYCH_TAXONOMY.md).

**Live (`SIMPLE_PROMPT=1`):** slim **6-move playbook** in
`core/technique_playbook.py` — not the fat 17-tech catalog.
Code picks ONE move via a clear WHEN tree; DeepSeek only writes the bubble.

**Prompt / how-to instructions are English only.** Chat bubbles may mirror ES/EN.

## Playbook (6 moves)

| Move | WHEN | NEVER |
|------|------|-------|
| **BOND** | Early / shy / reconnect — feel chosen | Unpaid nag, guilt, rival, crisis |
| **HEAT** | Horny / flirting / compliments | Therapist tone, cold sell stamp |
| **ASK PIC** | Msgs ~2–10, no fan photo yet | Same turn as paid lock pitch |
| **SELL LOCK** | REAL unpaid lock in chat | Invent lock, guilt, fake emergency |
| **HOLD FRAME** | Price / discount pushback | Begging, rent crisis, guilt |
| **REWARD** | Just tipped / unlocked | Instant upsell, rival FOMO |

Train execution (most important KPI):

```bash
python scripts/sim_mass.py --llm-fan --long --json out/sim.json
# Look at summary.move_hit_rate and per-move misses — tighten beats / WHEN tree
```

Soft enforce: if draft misses move signals → one LLM rewrite (`move-hit`) then warn.

## Input → Fase (packs = gates / logs)

| Input del fan | Fase | Pack |
|---------------|------|------|
| hola / hey / qué tal (temprano) | 1 Hook | `phase_hook` |
| engacho / dirty / "quiero ver…" | 2 Spiral → 3 Pull | `phase_spiral` → `phase_pull` |
| calor + free hecho / buy signal | 4 Close | `phase_close` |
| caro / later / nah | 5 Objection | `price_objection` → HOLD FRAME |
| acaba de comprar | 6 Reward | `reward_purchase` → REWARD |
| post-compra (15–45 min) | 7 Withdrawal | `post_sale_withdrawal` |
| silencio (nudge) | 8 Reengage | `phase_reengage` |
| PPV unpaid / delivery API | Hard gates | `ppv_unpaid` → SELL LOCK |

## Regla de oro

**One ACTIVE MOVE per bubble.** Never invent a second angle.

**SIMPLE live:** picker = `technique_playbook.pick_playbook_move` (via
`technique_policy.choose_move`). Edit WHEN/beats in `technique_playbook.py`
+ `personas/emma.md`. Pack `.md` edits do **not** change creative text.

**Legacy (`SIMPLE_PROMPT=0`):** fat scored catalog in `manipulation.py`.
