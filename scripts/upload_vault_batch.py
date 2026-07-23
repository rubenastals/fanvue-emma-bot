"""
Upload ranked vault photos to Fanvue (multipart API) and save mediaUuids.

Usage:
    python scripts/upload_vault_batch.py exports/vault_rank_20260716_170746/catalog.json
    python scripts/upload_vault_batch.py exports/vault_rank_YYYYMMDD_HHMMSS/catalog.json --limit 2

Requires OAuth tokens with write:media (already in .fanvue_tokens.json).
Idempotent: skips items that already have fanvue_media_uuid.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from api.fanvue_connector import FanvueConnector

_VAULT_PREFIX = (os.getenv("VAULT_FOLDER_PREFIX") or os.getenv("ACCOUNT_ID") or "Emma").strip()
_VAULT_PREFIX_TITLE = _VAULT_PREFIX[:1].upper() + _VAULT_PREFIX[1:]


def _level_folders() -> Dict[int, str]:
  prefix = _VAULT_PREFIX_TITLE
  return {
      1: f"{prefix}_L1_lingerie",
      2: f"{prefix}_L2_topless",
      3: f"{prefix}_L3_soft_nude",
      4: f"{prefix}_L4_open_nude",
      5: f"{prefix}_L5_fingers",
      6: f"{prefix}_L6_hardcore",
      7: f"{prefix}_L7_extreme",
  }


def _folder_for(item: Dict[str, Any]) -> str:
    level = int(item.get("level") or 0)
    folders = _level_folders()
    prefix = _VAULT_PREFIX_TITLE
    return folders.get(level, f"{prefix}_L{level or 'X'}_misc")


def _display_name(index: int, item: Dict[str, Any]) -> str:
    level = item.get("level", "?")
    score = item.get("score", "?")
    label = (item.get("vault_label") or item.get("content_type") or "shot").strip()
    label = "".join(c if c.isalnum() or c in " -_" else "" for c in label)[:40].strip()
    return f"{index:02d}_L{level}_s{score}_{label}"


def _price_cents(item: Dict[str, Any]) -> int:
    # Fanvue recommendedPrice is USD cents; we map our € tip 1:1 for now.
    eur = item.get("price_eur_suggested")
    if eur is None:
        return 0
    return max(0, min(50000, int(round(float(eur) * 100))))


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch upload vault catalog to Fanvue")
    ap.add_argument("catalog", type=str, help="Path to catalog.json from rank_vault_photos")
    ap.add_argument("--limit", type=int, default=0, help="Only upload first N pending items")
    ap.add_argument("--sleep", type=float, default=0.4, help="Pause between uploads (rate limit)")
    ap.add_argument(
        "--no-folder",
        action="store_true",
        help="Upload to vault root only (no level folders)",
    )
    args = ap.parse_args()

    catalog_path = Path(args.catalog).expanduser().resolve()
    if not catalog_path.is_file():
        raise SystemExit(f"Catalog not found: {catalog_path}")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog.get("items") or []
    if not items:
        raise SystemExit("Catalog has no items")

    fv = FanvueConnector()
    me = fv.get_current_user()
    print(f"→ Fanvue user: @{me.get('handle') or me.get('username') or me.get('uuid')}")
    print(f"→ Catalog: {catalog_path} ({len(items)} items)\n")

    # Ensure level folders up front
    if not args.no_folder:
        levels = sorted({int(it.get("level") or 0) for it in items if it.get("level")})
        for lvl in levels:
            folders = _level_folders()
            prefix = _VAULT_PREFIX_TITLE
            name = folders.get(lvl, f"{prefix}_L{lvl}_misc")
            fv.ensure_vault_folder(name)
            print(f"  folder ready: {name}")
        print()

    uploaded = 0
    skipped = 0
    failed = 0
    pending = [it for it in items if not it.get("fanvue_media_uuid")]
    if args.limit > 0:
        pending = pending[: args.limit]

    # Index for display names by original order in catalog
    order_index = {it["file"]: i for i, it in enumerate(items, 1)}

    for n, item in enumerate(pending, 1):
        path = Path(item.get("path") or "")
        if not path.is_file():
            # fall back to source_folder + file
            src = Path(catalog.get("source_folder") or "")
            path = src / item["file"]
        if not path.is_file():
            print(f"[{n}/{len(pending)}] ❌ missing file: {item.get('file')}")
            failed += 1
            continue

        idx = order_index.get(item["file"], n)
        name = _display_name(idx, item)
        folder = None if args.no_folder else _folder_for(item)
        caption = (item.get("caption") or "")[:5000]
        price_cents = _price_cents(item)

        print(
            f"[{n}/{len(pending)}] Uploading {path.name} → {folder or 'root'} "
            f"€{item.get('price_eur_suggested')} ...",
            flush=True,
        )
        try:
            result = fv.upload_file_to_vault(
                str(path),
                name=name,
                caption=caption,
                recommended_price_cents=price_cents or None,
                folder_name=folder,
                media_type="image",
            )
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
            failed += 1
            item["fanvue_upload_error"] = str(e)
            catalog_path.write_text(
                json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            continue

        item["fanvue_media_uuid"] = result["mediaUuid"]
        item["fanvue_status"] = result.get("status")
        item["fanvue_folder"] = result.get("folder")
        item["fanvue_name"] = result.get("name")
        item.pop("fanvue_upload_error", None)
        uploaded += 1
        print(f"  ✓ {result['mediaUuid']} status={result.get('status')}")

        # Persist after each success (safe for mass runs)
        catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Also update card file if present
        cards_dir = catalog_path.parent / "cards"
        card_path = cards_dir / f"{Path(item['file']).stem}.json"
        if card_path.is_file():
            try:
                card = json.loads(card_path.read_text(encoding="utf-8"))
                card["fanvue_media_uuid"] = result["mediaUuid"]
                card["fanvue_folder"] = result.get("folder")
                card["price_eur_suggested"] = item.get("price_eur_suggested")
                card_path.write_text(
                    json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

        if args.sleep > 0:
            time.sleep(args.sleep)

    already = sum(1 for it in items if it.get("fanvue_media_uuid")) - uploaded
    skipped = max(0, already)

    # Mapping file for the bot
    mapping = {
        "catalog": str(catalog_path),
        "items": [
            {
                "file": it["file"],
                "fanvue_media_uuid": it.get("fanvue_media_uuid"),
                "level": it.get("level"),
                "score": it.get("score"),
                "price_eur_suggested": it.get("price_eur_suggested"),
                "fanvue_folder": it.get("fanvue_folder"),
                "vault_label": it.get("vault_label"),
            }
            for it in items
            if it.get("fanvue_media_uuid")
        ],
    }
    map_path = catalog_path.parent / "fanvue_media_map.json"
    map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n✅ done. uploaded={uploaded} skipped_existing≈{skipped} failed={failed}"
    )
    print(f"✅ catalog updated: {catalog_path}")
    print(f"✅ media map: {map_path}")


if __name__ == "__main__":
    main()
