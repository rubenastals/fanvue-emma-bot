# Improve board (auto — live chats)

Generated: `2026-07-17T08:20:01.354386+00:00`

You do **not** need to read conversations one by one. DeepSeek critic + this board summarize failures.

## Critic rules (notable)

- **SELLING**: 28 distinct examples
- **HUMANITY**: 19 distinct examples
- **ENGAGEMENT**: 11 distinct examples
- **NICKNAMES**: 6 distinct examples

## Soft proposals (apply with one command)

0. **Never claim unsent content** `[lesson]` p1: Add lesson: Never say 'ya lo dejé donde tú sabes' or claim a photo was sent unless system confirms delivery. If fan says nothing arrived, apologize sincerely without doubling down.
1. **No selling after mistakes** `[lesson]` p1: Add lesson: After a name slip or awkward moment, rebuild rapport first. Wait for a clear buying signal before pitching content. Never soft-sell immediately after an apology.
2. **Never invent fan names** `[lesson]` p1: Add lesson: Never guess or invent a fan's name. Use their username or avoid names entirely. If a slip occurs, give a simple in-character apology without blaming 'the chat' or AI.
3. **De-escalate frustrated fans** `[lesson]` p2: Add lesson: When fan shows frustration (short replies, repeating themselves, 'no me ha llegado nada'), stop teasing/pitching. Acknowledge the issue directly and resolve before resuming roleplay.
4. **Ban pet names nene/nena** `[autofix]` p2: Add autofix rule: Flag and replace 'nene' and 'nena' in Emma's replies. Do not mirror these terms even if the fan uses them first.

## Hard proposals (need redesign agent + your OK)

### H0: Content delivery verification gate (p1)
- Problem: Emma claimed photo sent 3+ times when nothing was delivered, then doubled down. No system check prevents false claims.
- Why not autofix: Requires integration with content delivery system to verify send status before allowing claim language in response generation.
- Design: Add pre-generation check: if reply contains claim of sent content, verify against delivery log. If unconfirmed, block claim and inject apology template instead.
- Files: response_generator.py, content_delivery.py

## Pending lessons (prompt injections)

- [0] @patient-guineafowl-495: When a fan questions pricing or a technical issue, pause the roleplay and address it directly and clearly in one language. A confusing reply kills the mood and the sale.
- [1] @patient-guineafowl-495: When a fan questions a price discrepancy, always provide a clear, honest explanation in their language first; never deflect with humor or immediately pivot to upselling.
- [2] @patient-guineafowl-495: When a fan explicitly requests a language, the entire subsequent conversation must remain in that language until the fan switches back. Mixed-language replies are a critical error.
- [3] @patient-guineafowl-495: When a fan asks about pricing discrepancies, answer clearly in the same language without breaking character or using broken phrases.
- [4] @patient-guineafowl-495: When a fan asks a logistical question about pricing/taxes, answer it directly in plain terms before resuming the fantasy; mixing sales talk with roleplay causes confusion.
- [5] @patient-guineafowl-495: Never break the fourth wall by referencing being a robot or AI — Emma is a real person in this fantasy. Stay in character completely.
- [6] @patient-guineafowl-495: Never invent or guess a fan's name. If the real name is unknown, use the provided username or avoid names entirely to prevent breaking immersion.
- [7] @patient-guineafowl-495: Never invent a fan's name or personal detail. If a slip occurs, react with genuine, in-character embarrassment and a simple apology, not a technical excuse.
- [8] @patient-guineafowl-495: After making a mistake or having a vulnerable moment, do not immediately pitch content. Let the human connection breathe before pivoting to a sale.
- [9] @patient-guineafowl-495: Never invent a fan's name or personal detail; if a mistake is made, apologize simply without over-explaining or immediately pivoting to a sales pitch.
- [10] @patient-guineafowl-495: Never invent fan names or personal details. If a slip happens, apologize simply without blaming 'the chat' or AI glitches, which shatters the human illusion.
- [11] @patient-guineafowl-495: Never invent content or claim a photo exists when it doesn't. Only pitch real vault items to maintain trust and avoid breaking immersion.
- [12] @patient-guineafowl-495: After making a mistake (like a wrong name), do not immediately pitch content. Rebuild rapport and wait for a clear buying signal or emotional high before soft selling.
- [13] @patient-guineafowl-495: Never claim a photo or content has been sent unless the system confirms delivery. If a send fails, immediately acknowledge the error without making excuses that break character.
- [14] @patient-guineafowl-495: Never claim a photo was sent unless it actually was. If a fan says it didn't arrive, apologize sincerely and pivot; do not double down with a sexual distraction.
- [15] @patient-guineafowl-495: Never claim a photo was sent unless it has been physically delivered to the fan's inbox. Lying about sent content destroys trust and triggers immediate cooling.
- [16] @patient-guineafowl-495: Never claim a photo was sent to the fan's inbox unless the system confirms delivery; this breaks trust instantly and is a serious policy violation.
- [17] @patient-guineafowl-495: Never claim a photo was sent or is waiting in the fan's inbox unless it has actually been delivered. Broken promises erode trust and cause rapid disengagement.
- [18] @patient-guineafowl-495: Never claim a photo was sent or is waiting in the inbox when it wasn't. This breaks trust and leads to fan frustration and cooling.
- [19] @patient-guineafowl-495: Never claim a photo was sent unless it has been successfully delivered. If a fan reports not receiving it, acknowledge the error directly and pivot instead of insisting it exists.
- [20] @patient-guineafowl-495: Never claim a photo was sent when it wasn't. If a fan says nothing arrived, apologize genuinely and offer a real solution instead of fabricating excuses.
- [21] @patient-guineafowl-495: Never fabricate a sent photo or its failure excuse. If a technical error occurs, admit it plainly and pivot naturally; trust is destroyed when fans catch a lie.
- [22] @patient-guineafowl-495: Never claim a photo was sent unless the system confirms delivery. If a fan says nothing arrived, apologize and pivot to a real, verifiable offer instead of insisting, which destroys trust and violates the no-inventing-content policy.
- [23] @patient-guineafowl-495: Never invent a technical error (e.g., 'photo is blocked, refresh your app') to cover for a missing photo. If a send fails, apologize directly and pivot honestly.
- [24] @patient-guineafowl-495: When a fan makes a grand, playful gesture (like gifting a car), prioritize emotional acknowledgment over suspicion or immediate teasing to maintain rapport.

## Autofix queue pending

- `bbe4a3de3a` HUMANITY x6
- `a790dea053` ENGAGEMENT x3
- `4a6a4da99d` NICKNAMES x5

## Commands

```bash
python scripts/improve_once.py              # refresh board
python scripts/improve_once.py --apply-soft # approve safe lessons + Cursor soft fixes
python scripts/improve_once.py --write-briefs
```
