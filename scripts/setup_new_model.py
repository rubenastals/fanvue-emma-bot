"""
Scaffold a second Fanvue model (persona + DB row + vault map path).

Usage:
    python scripts/setup_new_model.py sofia \\
        --handle im.sofiacarter \\
        --name "Sofia Reyes" \\
        --age 22 \\
        --from "Miami, FL" \\
        --body "petite, toned, sun-kissed" \\
        --vibe "LA party girl — bratty, loud, loves attention"

Then:
    ACCOUNT_ID=sofia python scripts/oauth_login.py
    # rank + upload photos, sync vault — see docs/SETUP_SEGUNDA_MODELO.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

TEMPLATE = (_ROOT / "personas" / "TEMPLATE.md").read_text(encoding="utf-8")
EMMA_REF = (_ROOT / "personas" / "emma.md").read_text(encoding="utf-8")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else "Model"


def _build_persona(
    *,
    full_name: str,
    age: int,
    body: str,
    origin: str,
    vibe: str,
    pet_names: str,
    dirty_phrases: str,
    tone: str,
) -> str:
    name = _first_name(full_name)
    personality = (
        f"You're {full_name.split()[0]} from {origin}. {vibe.strip()}"
        if vibe.strip()
        else f"You're {full_name.split()[0]} from {origin}."
    )
    text = TEMPLATE
    replacements = {
        "[FULL NAME]": full_name,
        "[AGE]": str(age),
        "[BODY TYPE — e.g. petite, thick, curvy]": body,
        "[PERSONALITY DESCRIPTION — 2-3 sentences about her vibe, backstory, attitude]": personality,
        "[LIST HER PREFERRED PET NAMES — e.g. baby, babe, handsome, trouble, honey, daddy]": pet_names,
        "[ADD HER FAVORITE DIRTY PHRASES — keep her voice, not generic]": dirty_phrases,
        "[HER TONE — e.g. playful and bratty / sweet then suddenly wild / confident and teasing]": tone,
        "[HER TONE — e.g. Confident, playful, a little bratty, very sexual but warm]": tone,
        "[NAME]": name,
        "[HER ANSWER IN HER VOICE]": f"hey {pet_names.split(',')[0].strip()}… just got home, thinking about you",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Pull WhatsApp-style rules from Emma (live brain) — shared mechanics, different voice.
    whatsapp_block = ""
    if "Core Style — WhatsApp girlfriend" in EMMA_REF:
        start = EMMA_REF.index("Core Style — WhatsApp girlfriend")
        end = EMMA_REF.index("Strict Rules:", start)
        whatsapp_block = EMMA_REF[start:end].strip()
    if whatsapp_block:
        text = text.replace(
            "Core Style — Text like a horny girlfriend on her phone:",
            whatsapp_block,
            1,
        )
    return text.strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold a new Fanvue model account")
    ap.add_argument("account_id", help="Short id, e.g. sofia (used as ACCOUNT_ID)")
    ap.add_argument("--handle", required=True, help="Fanvue creator handle, e.g. im.sofiacarter")
    ap.add_argument("--name", required=True, help='Full display name, e.g. "Sofia Reyes"')
    ap.add_argument("--age", type=int, required=True)
    ap.add_argument("--from", dest="origin", required=True, help='City/country, e.g. "Miami, FL"')
    ap.add_argument("--body", default="curvy, confident", help="Body type one-liner")
    ap.add_argument("--vibe", default="", help="2-3 sentence personality / backstory")
    ap.add_argument(
        "--pet-names",
        default="baby, babe, handsome, trouble, honey",
        help="Comma-separated pet names",
    )
    ap.add_argument(
        "--dirty",
        default="wet, dripping, want you inside me, touching myself thinking of you",
        help="Dirty phrases in her voice",
    )
    ap.add_argument(
        "--tone",
        default="playful, bratty, warm, very sexual",
        help="Tone adjectives",
    )
    ap.add_argument("--force", action="store_true", help="Overwrite existing persona file")
    args = ap.parse_args()

    aid = _slug(args.account_id)
    if not aid:
        raise SystemExit("account_id must contain letters/numbers")

    persona_path = _ROOT / "personas" / f"{aid}.md"
    if persona_path.exists() and not args.force:
        raise SystemExit(f"Persona already exists: {persona_path} (use --force)")

    persona_path.write_text(
        _build_persona(
            full_name=args.name,
            age=args.age,
            body=args.body,
            origin=args.origin,
            vibe=args.vibe,
            pet_names=args.pet_names,
            dirty_phrases=args.dirty,
            tone=args.tone,
        ),
        encoding="utf-8",
    )

    map_path = _ROOT / "data" / f"{aid}_fanvue_media_map.json"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    if not map_path.exists():
        map_path.write_text(
            json.dumps({"version": 1, "account_id": aid, "items": []}, indent=2) + "\n",
            encoding="utf-8",
        )

    os.environ["ACCOUNT_ID"] = aid
    os.environ["FANVUE_CREATOR_HANDLE"] = args.handle
    os.environ["PERSONA_KEY"] = aid

    from db.schema import init_schema

    init_schema(seed_account=True)

    rel_persona = f"personas/{aid}.md"
    rel_map = f"data/{aid}_fanvue_media_map.json"
    prefix = aid[:1].upper() + aid[1:]

    print()
    print("=" * 60)
    print(f"OK: model '{aid}' scaffolded")
    print("=" * 60)
    print(f"  persona:     {rel_persona}")
    print(f"  vault map:   {rel_map}")
    print(f"  DB account:  {aid} (handle={args.handle})")
    print()
    print("Next steps:")
    print()
    print("1) Edit the persona (examples, voice tweaks):")
    print(f"     {rel_persona}")
    print()
    print("2) OAuth as the NEW creator (same FANVUE_CLIENT_ID/SECRET is fine):")
    print(f"     ACCOUNT_ID={aid} python scripts/oauth_login.py")
    print()
    print("3) Rank + upload PPV photos for this model:")
    print("     python scripts/rank_vault_photos.py /path/to/her/photos --copy-ordered")
    print(f"     ACCOUNT_ID={aid} VAULT_FOLDER_PREFIX={prefix} \\")
    print("       python scripts/upload_vault_batch.py exports/vault_rank_*/catalog.json")
    print(f"     mv exports/vault_rank_*/fanvue_media_map.json {rel_map}")
    print(f"     ACCOUNT_ID={aid} FANVUE_MEDIA_MAP={rel_map} python scripts/sync_vault_to_pg.py")
    print()
    print("4) Deploy a second poller (Railway / Docker) with:")
    print(f"     ACCOUNT_ID={aid}")
    print(f"     PERSONA_FILE={rel_persona}   # optional if personas/{aid}.md exists")
    print(f"     FANVUE_MEDIA_MAP={rel_map}")
    print(f"     VAULT_FOLDER_PREFIX={prefix}")
    print("     ELEVENLABS_VOICE_ID=<her voice>")
    print("     DATABASE_URL / REDIS_URL = same as Emma (partitioned by account_id)")
    print()
    print("Full guide: docs/SETUP_SEGUNDA_MODELO.md")
    print()


if __name__ == "__main__":
    main()
