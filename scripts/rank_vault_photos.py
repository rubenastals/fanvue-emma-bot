"""
Analyze vault photos with Grok Vision (detailed captions + sell ladder),
sort least → most explicit, export catalog for Fanvue + chat PPV.

Usage:
    python scripts/rank_vault_photos.py "C:\\path\\to\\photos" --copy-ordered

Requires .env:
    XAI_API_KEY=...
    XAI_VISION_MODEL=grok-4.3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from openai import OpenAI

from config import config
from utils.joycaption_client import (
    SELL_LADDER,
    analyze_image,
    backend_info,
    is_configured,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

NORMALIZE_SYSTEM = f"""You normalize Fanvue vault photo scores so near-duplicate shots stay consistent.
Use this sell ladder exactly:
{SELL_LADDER}

Return ONLY valid JSON:
{{
  "ranked": [
    {{
      "file": "exact filename",
      "level": 3,
      "score": 5,
      "price_eur_suggested": 10,
      "content_type": "...",
      "vault_label": "short English vault label",
      "reason": "one short sentence"
    }}
  ]
}}

Rules:
- Include EVERY file exactly once.
- Order "ranked" from LEAST to MOST explicit (score ascending, then level).
- Keep scores inside each level's range.
- Near-identical captions: same level/score unless a real visible difference exists (legs open vs closed, toy, fingers, fluids).
- Prefer under-classifying if unsure.
- price_eur_suggested inside that level's € range.
"""


def _list_images(folder: Path) -> List[Path]:
    files = [
        p
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    if not files:
        raise SystemExit(f"No images found in {folder}")
    return files


def _grok_text() -> OpenAI:
    if not config.XAI_API_KEY:
        raise SystemExit("XAI_API_KEY missing")
    return OpenAI(api_key=config.XAI_API_KEY, base_url=config.XAI_BASE_URL)


def _normalize_batch(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Second pass: Grok text normalizes scores across similar photos."""
    blocks = []
    for it in items:
        blocks.append(
            f"FILE: {it['file']}\n"
            f"VISION_LEVEL: {it.get('level')} SCORE: {it.get('score')} "
            f"PRICE: {it.get('price_eur_suggested')} TYPE: {it.get('content_type')}\n"
            f"DISTINGUISH: {it.get('distinguishing_detail')}\n"
            f"VISIBLE: {json.dumps(it.get('visible') or {}, ensure_ascii=False)}\n"
            f"REASON: {it.get('reason')}\n"
            f"CAPTION:\n{it.get('caption')}"
        )
    messages = [
        {"role": "system", "content": NORMALIZE_SYSTEM},
        {
            "role": "user",
            "content": "Normalize and rank least → most explicit:\n\n"
            + "\n\n---\n\n".join(blocks),
        },
    ]
    resp = _grok_text().chat.completions.create(
        model=config.XAI_VISION_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=4000,
    )
    text = (resp.choices[0].message.content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            print("⚠ Normalize failed; sorting by vision scores only.")
            return sorted(
                items,
                key=lambda x: (int(x.get("score") or 0), int(x.get("level") or 0), x["file"]),
            )
        payload = json.loads(m.group(0))

    by_file = {it["file"]: it for it in items}
    merged: List[Dict[str, Any]] = []
    seen = set()
    for row in payload.get("ranked") or []:
        fname = row.get("file")
        if fname not in by_file:
            continue
        base = dict(by_file[fname])
        for k in (
            "level",
            "score",
            "price_eur_suggested",
            "content_type",
            "vault_label",
            "reason",
        ):
            if row.get(k) is not None:
                base[k] = row[k]
        seen.add(fname)
        merged.append(base)
    for it in items:
        if it["file"] not in seen:
            merged.append(it)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description="Grok Vision vault catalog + sell ladder")
    ap.add_argument("folder", type=str, help="Folder with photos")
    ap.add_argument("--copy-ordered", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--skip-normalize",
        action="store_true",
        help="Skip batch normalize pass (vision scores only)",
    )
    args = ap.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        raise SystemExit(f"Not a folder: {folder}")
    if not is_configured():
        raise SystemExit(f"XAI not configured: {backend_info()}")

    images = _list_images(folder)
    if args.limit > 0:
        images = images[: args.limit]

    print(f"→ Backend: {backend_info()}")
    print(f"→ Photos:  {len(images)} in {folder}\n")

    analyzed: List[Dict[str, Any]] = []
    for i, path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] Analyzing {path.name} ...", flush=True)
        try:
            data = analyze_image(str(path))
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
            raise SystemExit(1) from e
        data["file"] = path.name
        data["path"] = str(path)
        analyzed.append(data)
        print(
            f"  ✓ L{data.get('level')} score={data.get('score')} "
            f"€{data.get('price_eur_suggested')} | {data.get('content_type')} | "
            f"{(data.get('caption') or '')[:100]}…"
        )

    if args.skip_normalize:
        ranked = sorted(
            analyzed,
            key=lambda x: (int(x.get("score") or 0), int(x.get("level") or 0), x["file"]),
        )
    else:
        print("\n→ Normalizing scores across similar shots (Grok)...")
        ranked = _normalize_batch(analyzed)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(_ROOT) / "exports" / f"vault_rank_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog = {
        "created_utc": stamp,
        "source_folder": str(folder),
        "caption_backend": backend_info(),
        "order": "least_to_most_explicit",
        "sell_ladder": SELL_LADDER.strip(),
        "items": ranked,
    }
    catalog_path = out_dir / "catalog.json"
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Per-file caption cards for chat engine later
    cards_dir = out_dir / "cards"
    cards_dir.mkdir(exist_ok=True)
    for row in ranked:
        card = {
            "file": row["file"],
            "vault_label": row.get("vault_label") or row.get("content_type"),
            "level": row.get("level"),
            "score": row.get("score"),
            "price_eur_suggested": row.get("price_eur_suggested"),
            "content_type": row.get("content_type"),
            "distinguishing_detail": row.get("distinguishing_detail"),
            "caption": row.get("caption"),
            "visible": row.get("visible"),
        }
        stem = Path(row["file"]).stem
        (cards_dir / f"{stem}.json").write_text(
            json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    lines = [
        "Fanvue vault upload order (LEAST → MOST explicit)",
        f"Source: {folder}",
        f"Generated: {stamp} UTC | {backend_info()}",
        "",
        "Level | Score | € | Content",
        "1 Lingerie/tease | 2-3 | 3-5",
        "2 Topless | 4 | 6-8",
        "3 Soft nude closed | 5-6 | 9-12",
        "4 Open nude / soft CU | 7 | 15-20",
        "5 Fingers/touching | 8 | 25-30",
        "6 Dildo/hard spread | 9 | 35-45",
        "7 Extreme dirty | 10 | 50-70",
        "",
    ]
    for i, row in enumerate(ranked, 1):
        lines.append(
            f"{i:02d}. L{row.get('level')} score={row.get('score')}/10 "
            f"€{row.get('price_eur_suggested')} — {row['file']}"
        )
        lines.append(f"    type: {row.get('content_type')} | {row.get('vault_label', '')}")
        lines.append(f"    uniq: {row.get('distinguishing_detail', '')}")
        lines.append(f"    why:  {row.get('reason', '')}")
        lines.append(f"    cap:  {(row.get('caption') or '')[:280]}")
        lines.append("")
    order_path = out_dir / "UPLOAD_ORDER.txt"
    order_path.write_text("\n".join(lines), encoding="utf-8")

    if args.copy_ordered:
        ordered_dir = out_dir / "ordered"
        ordered_dir.mkdir(exist_ok=True)
        for i, row in enumerate(ranked, 1):
            src = Path(row["path"])
            score = row.get("score", 0)
            level = row.get("level", 0)
            dest = ordered_dir / f"{i:02d}_L{level}_s{score}_{src.name}"
            shutil.copy2(src, dest)
        print(f"→ Ordered copies → {ordered_dir}")

    print(f"\n✅ catalog: {catalog_path}")
    print(f"✅ order:    {order_path}")
    print(f"✅ cards:    {cards_dir} ({len(ranked)} files)")
    print("\nUpload / sell in that order (01 = softest).")


if __name__ == "__main__":
    main()
