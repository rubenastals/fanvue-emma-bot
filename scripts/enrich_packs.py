"""
Offline pack enrichment from critic history + pending lessons + DeepSeek.

Writes packs/*.md only. Never injects Soft lessons into the live prompt.
Keep one pack / turn; respect packs/_index.json budget_chars.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env before config
_env = ROOT / ".env"
if _env.is_file():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from config import Config  # noqa: E402
from openai import OpenAI  # noqa: E402

PACKS_DIR = ROOT / "packs"
INDEX_PATH = PACKS_DIR / "_index.json"
LESSONS_PATH = ROOT / ".lessons.json"
BOARD_PATH = ROOT / ".improve_board.json"
CONVO_DIR = ROOT / "logs" / "conversations"

# Hard anti-regressions that MUST survive enrichment (past production failures).
ANTI = {
    "_global": [
        "Never invent a fan's real name; use CLIENT CARD name only if present, almost never stamp it",
        "Never claim media sent unless TURN FACTS / API say so this turn",
        "Never invent app glitches, blocked photos, or bracket Transmit lines",
        "Mirror his language (ES/EN); one language per reply",
        "Banned: caro/papi/nena/nene — prefer babe/baby/handsome/cielo sparingly",
        "Max 3 lines; end with a question when engaging; 2–3 emojis max",
        "Do not paste Soft-lesson essays or multi-technique stacks",
    ],
    "phase_hook": [
        "No hard sell / price in first 1–2 replies unless he begs content",
        "Love-bomb + make him feel chosen; mirror energy",
    ],
    "phase_spiral": [
        "Escalate sensory desire; plant purchase seed without store voice",
        "No phone/IG/IRL meetup logistics",
    ],
    "phase_pull": [
        "Execute ONLY the ACTIVE TECHNIQUE banner — one technique, not three",
        "Stay the prize; never beg",
    ],
    "phase_close": [
        "If paid lock attaches: fire with first bubble — no permission ask",
        "Never offer free/gratis instead; never invent customs/videos we lack",
    ],
    "price_objection": [
        "No new cheaper lock; one STEP only (Guilt→Ego→FOMO→Cold)",
        "If he asks tax/price math, that is billing_clarify — not this pack",
    ],
    "reward_purchase": [
        "NO new unlock pitch this turn; make spend feel like status",
    ],
    "post_sale_withdrawal": [
        "Warm but busy; no new PPV unless he clearly asks",
    ],
    "phase_reengage": [
        "FOMO/miss-you without inventing a delivered photo",
    ],
    "delivery_missing": [
        "API says gift NOT in chat — never claim you already gifted",
        "If no attach: apologize once, no tech excuses",
    ],
    "delivery_scroll": [
        "Free photo IS in chat — tell him to scroll; do not re-gift",
    ],
    "ppv_unpaid": [
        "Point to the waiting unpaid lock only; never stack a second PPV",
    ],
    "ask_free_first": [
        "Gift is FREE unlocked if attached — never say locked/pay",
        "No pose-caption essays",
    ],
    "react_fan_media": [
        "React to HIS media first; no PPV/price this turn",
    ],
    "billing_clarify": [
        "Answer billing/tax plainly first; Fanvue adds VAT — no guilt/FOMO while confused",
    ],
}

PHASE_PACKS = [
    "phase_hook",
    "phase_spiral",
    "phase_pull",
    "phase_close",
    "price_objection",
    "reward_purchase",
    "post_sale_withdrawal",
    "phase_reengage",
    "delivery_missing",
    "delivery_scroll",
    "ppv_unpaid",
    "ask_free_first",
    "react_fan_media",
    "billing_clarify",
]


def _budget() -> int:
    try:
        idx = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return int(idx.get("budget_chars") or 1400)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 1400


def _pending_lessons(limit: int = 40) -> list[str]:
    out: list[str] = []
    if BOARD_PATH.is_file():
        try:
            board = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
            for item in board.get("pending_lessons") or []:
                t = (item.get("text") or "").strip()
                if t:
                    out.append(t)
        except (OSError, json.JSONDecodeError):
            pass
    if LESSONS_PATH.is_file():
        try:
            data = json.loads(LESSONS_PATH.read_text(encoding="utf-8"))
            for item in data.get("global_pending") or []:
                t = (item.get("text") if isinstance(item, dict) else str(item)).strip()
                if t:
                    out.append(t)
        except (OSError, json.JSONDecodeError):
            pass
    # dedupe keep order
    seen = set()
    uniq = []
    for t in out:
        k = t.lower()[:80]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    return uniq[:limit]


def _critic_samples(limit_per_rule: int = 5) -> dict[str, list[str]]:
    by: dict[str, list[str]] = defaultdict(list)
    if not CONVO_DIR.is_dir():
        return {}
    for path in sorted(CONVO_DIR.glob("*.jsonl"))[-3:]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            for e in r.get("errors") or []:
                rule = str(e.get("rule") or "?")
                what = (e.get("what") or "").replace("\n", " ").strip()
                if what and len(by[rule]) < limit_per_rule:
                    by[rule].append(what[:200])
    return dict(by)


def _map_evidence_for_pack(pack_id: str, lessons: list[str], critic: dict[str, list[str]]) -> str:
    keys = {
        "delivery_missing": ("sent", "delivery", "photo", "gift", "glitch", "inbox"),
        "delivery_scroll": ("scroll", "sent", "gift", "inbox"),
        "ppv_unpaid": ("unlock", "lock", "ppv", "paid", "stack"),
        "ask_free_first": ("free", "gift", "regal", "l0"),
        "react_fan_media": ("his photo", "media", "car", "acknowledge", "react"),
        "billing_clarify": ("price", "tax", "billing", "vat", "fee", "€"),
        "phase_hook": ("greeting", "name", "language", "hola", "first"),
        "phase_spiral": ("fantasy", "escalat", "sensory", "dirty"),
        "phase_pull": ("guilt", "scarcity", "technique", "manipul"),
        "phase_close": ("sale", "lock", "unlock", "fomo", "pitch"),
        "price_objection": ("expensive", "objection", "reject", "cheap"),
        "reward_purchase": ("bought", "purchase", "reward", "liked"),
        "post_sale_withdrawal": ("withdrawal", "busy", "disappear", "after sale"),
        "phase_reengage": ("silent", "nudge", "reengage", "miss"),
    }.get(pack_id, ())
    picked = []
    for t in lessons:
        low = t.lower()
        if any(k in low for k in keys) or pack_id.startswith("phase"):
            if any(k in low for k in keys) or any(
                w in low for w in ("name", "sent", "photo", "language", "pitch", "trust")
            ):
                picked.append(t)
        if len(picked) >= 8:
            break
    # always include top global trust lessons
    for t in lessons:
        low = t.lower()
        if any(w in low for w in ("never invent", "never claim a photo", "name", "language")):
            if t not in picked:
                picked.append(t)
        if len(picked) >= 12:
            break
    crit_bits = []
    for rule in ("SELLING", "HUMANITY", "NICKNAMES", "LANGUAGE", "ENGAGEMENT"):
        for s in critic.get(rule, [])[:2]:
            crit_bits.append(f"[{rule}] {s}")
    return "LESSONS:\n- " + "\n- ".join(picked[:10] or lessons[:6]) + "\n\nCRITIC:\n- " + "\n- ".join(
        crit_bits[:8]
    )


def _enrich_one(client: OpenAI, pack_id: str, current: str, evidence: str, budget: int) -> str:
    anti = ANTI.get("_global", []) + ANTI.get(pack_id, [])
    body_budget = max(400, budget - 80)  # leave room for SITUATION PACK header
    system = (
        "You enrich ONE Fanvue DM situation pack for Emma Carter.\n"
        "Output ONLY markdown for that pack. No preamble.\n"
        "Format EXACTLY:\n"
        f"# {pack_id}\n"
        "PHASE: (one short line if sales phase, else omit)\n"
        "MUST:\n- ...\n"
        "SHOULD:\n- ...\n"
        "NEVER:\n- ...\n"
        "VOICE (optional 1-2 example lines he should sound like — short):\n"
        "- ES: ...\n"
        "- EN: ...\n"
        f"Hard limit: under {body_budget} characters total.\n"
        "Firm bullets. No essays. No Soft-lesson dumps. No multi-technique stacks.\n"
        "Bake anti-regression rules into NEVER/MUST — they are non-negotiable.\n"
        "Use critic history to sharpen traps she fell into before.\n"
    )
    user = (
        f"PACK ID: {pack_id}\n"
        f"CURRENT PACK:\n{current}\n\n"
        f"ANTI-REGRESSION (must keep):\n- " + "\n- ".join(anti) + "\n\n"
        f"HISTORY EVIDENCE:\n{evidence}\n\n"
        "Rewrite a richer but still short pack. Keep operational (what to do THIS turn)."
    )
    kwargs = {
        "model": getattr(Config, "DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": 900,
    }
    if getattr(Config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = client.chat.completions.create(**kwargs)
    text = (resp.choices[0].message.content or "").strip()
    # strip fences
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    if not text.startswith("#"):
        text = f"# {pack_id}\n{text}"
    # force heading
    text = re.sub(r"^#\s+\S+", f"# {pack_id}", text, count=1)
    if len(text) > body_budget:
        text = text[: body_budget - 20].rstrip() + "\n…"
    return text


def _fallback_enrich(pack_id: str, current: str) -> str:
    """Deterministic enrichment if API unavailable — still upgrades packs."""
    anti = ANTI.get(pack_id, [])
    global_n = [
        "Invent names / wrong names",
        "Claim media sent without TURN FACTS",
        "Fake glitches / Transmit brackets",
        "Mix ES+EN in one reply",
        "caro/papi/nena/nene",
        "Soft-lesson essays or 3 techniques at once",
    ]
    extra_never = "\n".join(f"- {x}" for x in (anti + global_n)[:8])
    if "NEVER:" in current:
        if "Invent names" in current or "TURN FACTS" in current:
            return current.strip()
        return current.rstrip() + "\n" + extra_never
    return (
        current.rstrip()
        + "\n\nNEVER (anti-regression):\n"
        + extra_never
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-deepseek", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--budget", type=int, default=0)
    args = ap.parse_args()

    budget = args.budget or _budget()
    # Raise index budget so enriched packs fit (split schemas → room to grow)
    if not args.dry_run and INDEX_PATH.is_file():
        idx = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        if int(idx.get("budget_chars") or 0) < 1400:
            idx["budget_chars"] = 1400
            INDEX_PATH.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
            print("index budget_chars -> 1400")
            budget = 1400

    lessons = _pending_lessons()
    critic = _critic_samples()
    targets = args.only or PHASE_PACKS
    client = None
    if not args.no_deepseek and (Config.DEEPSEEK_API_KEY or "").strip():
        client = OpenAI(
            api_key=Config.DEEPSEEK_API_KEY,
            base_url=Config.DEEPSEEK_BASE_URL,
        )
    else:
        print("DeepSeek unavailable — using deterministic anti-regression enrich")

    for pack_id in targets:
        path = PACKS_DIR / f"{pack_id}.md"
        if not path.is_file():
            print("skip missing", pack_id)
            continue
        current = path.read_text(encoding="utf-8").strip()
        evidence = _map_evidence_for_pack(pack_id, lessons, critic)
        if client:
            try:
                new = _enrich_one(client, pack_id, current, evidence, budget)
                print(f"OK deepseek {pack_id} ({len(new)} chars)")
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {pack_id}: {exc} — fallback")
                new = _fallback_enrich(pack_id, current)
        else:
            new = _fallback_enrich(pack_id, current)
            print(f"OK fallback {pack_id} ({len(new)} chars)")
        if args.dry_run:
            print("---", pack_id, "---")
            print(new[:500])
            continue
        path.write_text(new.rstrip() + "\n", encoding="utf-8")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
