# Técnicas → Fases (Emma)

El playbook largo NO se pega entero al modelo. Las **10 leyes** viven en CORE.
Cada **fase** es un pack; el router elige uno por turno según el input.

## Mapa técnico

| Técnica | Dónde se aplica | Pack |
|---------|-----------------|------|
| Love Bombing | Fase 1 + Fase 3 (T1) + Fase 6 + Fase 8 | `phase_hook`, `phase_pull`, `reward_purchase`, `phase_reengage` |
| Withdrawal | Fase 3 (T1) + Fase 7 + Fase 5 Step 4 | `phase_pull`, `post_sale_withdrawal`, `price_objection` |
| Intermittent Reinforcement | Fase 3 (T2) + Fase 7 | `phase_pull`, `post_sale_withdrawal` |
| Guilt Trip | Fase 3 (T3) + Fase 5 Step 1 | `phase_pull`, `price_objection` |
| Scarcity + FOMO | Fase 3 (T4) + Fase 4 | `phase_pull`, `phase_close` |
| Ego Challenge | Fase 3 (T5) + Fase 5 Step 2 | `phase_pull`, `price_objection` |
| Gaslighting | Fase 3 (T6) | `phase_pull` |
| Future Faking | Fase 2 + Fase 3 (T7) | `phase_spiral`, `phase_pull` |
| Price Objection Script (4 pasos) | Fase 5 | `price_objection` |
| Reengagement | Fase 8 | `phase_reengage` |

## Input → Fase

| Input del fan | Fase | Pack |
|---------------|------|------|
| hola / hey / qué tal (temprano) | 1 Hook | `phase_hook` |
| engacho / dirty / "quiero ver…" | 2 Spiral → 3 Pull | `phase_spiral` → `phase_pull` |
| calor + free hecho / buy signal | 4 Close | `phase_close` |
| caro / later / nah | 5 Objection | `price_objection` |
| acaba de comprar | 6 Reward | `reward_purchase` |
| post-compra (15–45 min) | 7 Withdrawal | `post_sale_withdrawal` |
| silencio (nudge) | 8 Reengage | `phase_reengage` |
| PPV unpaid / delivery API | Hard gates | `ppv_unpaid`, `delivery_*` |

## Regla de oro

En `phase_pull`: **una sola técnica por mensaje**.
En `price_objection`: **un solo step por turno** (1→2→3→4 across turns).

**SIMPLE live (`SIMPLE_PROMPT=1`):** cada turno creativo recibe un
**ACTIVE MOVE** corto vía `core/technique_policy.py` (picker =
`manipulation.pick_technique`). Casuística = código
(`intent_router` / `technique_policy` / `poll_inbox` / `scheme_guard`)
o una regla en `personas/emma.md`. Editar `packs/*.md` **no** cambia el
texto creativo (solo gates/logs). Editar how-tos en `manipulation.py`
sí cambia el ACTIVE MOVE.

**Legacy (`SIMPLE_PROMPT=0`):** banner gordo + pack `.md`.
