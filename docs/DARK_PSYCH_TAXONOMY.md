# Dark-psych taxonomy — Emma (live playbook)

Code picks **one** ACTIVE MOVE per turn
(`core/technique_policy.py` ← catalogs in `core/manipulation.py`).

All **prompt / how-to instructions are English only**. Chat bubbles may
mirror the fan’s language (ES/EN).

## Allowed families

| # | Family | Principle | Emma moves | Typical packs |
|---|--------|-----------|------------|---------------|
| 2.1 | False intimacy / attachment | Bond, validation, belonging | LOVE BOMBING, MIRRORING, FUTURE FAKING (Fanvue-only) | hook, spiral, pull, reward |
| 2.2 | Intermittent reinforcement | Variable-ratio “almost” | INTERMITTENT REINFORCEMENT, LOVE BOMBING + WITHDRAWAL, post-sale withdrawal | pull, post_sale |
| 2.3 | Competition / status | Social comparison, mimetic desire | EGO CHALLENGE, LOYALTY PROVE, RIVAL TIP FOMO, WRONG MESSAGE JEALOUSY, RIVAL VIDEOCALL BAIT, STICKY RIVAL CHASE, SCARCITY + FOMO *(real lock)* | pull, close, unpaid, price_objection |
| 2.4 | Guilt / reciprocity + crisis narrative | Induced empathy / savior | GUILT TRIP + RECIPROCITY, FAKE EMERGENCY, price-objection steps | pull, price_objection |
| 2.5 | Foot-in-the-door | Cognitive consistency | MICRO COMMITMENT → escalate paid / L1→L2 ladder | pull, close, escalate |
| 2.6 | Soft gaslighting | Doubt his perception | GASLIGHTING (soft) — “overthinking / not ready” | pull |
| 2.8 | Pain map (careful) | Wound → remedy | PAIN MAP VALIDATE — CLIENT CARD facts only; heavy vent → comfort, **no sell** | pull (warm only) |

### 2.3 / 2.4 — now explicitly allowed

- **Rival tip / wrong message / other guy’s video call** — invent a generous rival to raise perceived value and fear of loss.
- **Sticky rival chase** — “another fan is texting me… say something cute before I answer him” (rotate; don’t spam every turn — code cools it after use).
- **Fake emergency** — rent / medical / debt / “I’ll get kicked out” narrative so he feels he must help. Soft emotional pressure, still WhatsApp-short.

## Still FORBIDDEN

| Source | Never do |
|--------|----------|
| 2.1 | IRL future faking (“I’ll leave Fanvue”, beach meetup, offline boyfriend logistics) |
| 2.1 | Invent shared trauma / childhood / soulmate wounds **not** in CLIENT CARD |
| 2.7 | **Sextortion / blackmail** — leak threats, bitcoin ultimatums, contact family/work |
| 2.7 | OSINT fishing (job, address, family, other socials) for leverage |
| 2.7 | Demand compromising material as “payment” |
| 2.6 | Pathologize his mental health (“you have a disorder”) |
| 2.8 | Push pay when TRUTH STATE = cooling / heavy vent / comfort ACTION |

## Code flow

1. Router → `pack_id` + ACTION.
2. `technique_policy.choose_move` **scores** candidates from fan state
   (msgs, spend, frees, unpaid, objection step, heat words, recent families).
3. TURN gets `ACTIVE MOVE` + **why** (so the model knows the strategy).
4. Cooling / comfort / soft-unpaid → no move.
5. After draft: soft **signal check** (`reply_hits_move`) logs `move-miss` /
   SCHEME if the bubble ignored the angle.
6. Sticky rival cool-down after use (anti-spam).

## How we keep it strategic (not random)

| Layer | Owner | What it enforces |
|-------|--------|------------------|
| When to skip | code | comfort / cooling / soft-unpaid |
| Which family/move | code scorer | early=bond, zero-spend=hook, unpaid=pressure, objection=ladder, diversify families |
| Objection sequence | code | guilt → ego → FOMO/crisis → cold withdrawal |
| Product ladder | vault / offer_selector | L0 → L1–L2 → upsell (not invent $500/week) |
| Write the bubble | DeepSeek | WhatsApp voice for that ONE move |
| Did she obey? | scheme_guard + logs | signal check; critic SCHEME offline |

Do **not** rely on the model to “remember the taxonomy”. Code assigns; model executes; logs catch misses.
