"""
Re-upload vault catalog after stripping C2PA / AI provenance markers.

Fanvue labels WaveSpeed JPEGs as "modified by AI" because of APP11 C2PA.
This script: strip → upload new → delete old UUID → update catalog/map/cards
and remap fan_memory sent_media_uuids.

Usage:
    python scripts/reupload_vault_clean.py exports/vault_rank_20260716_170746/catalog.json
    python scripts/reupload_vault_clean.py exports/vault_rank_20260716_170746/catalog.json --limit 2
    python scripts/reupload_vault_clean.py ... --keep-old   # do not delete old media
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from api.fanvue_connector import FanvueConnector
from scripts.upload_vault_batch import (
    _VAULT_PREFIX_TITLE,
    _display_name,
    _folder_for,
    _level_folders,
    _price_cents,
)
from utils.strip_c2pa import has_c2pa


def _resolve_path(catalog: Dict[str, Any], item: Dict[str, Any]) -> Path:
    path = Path(item.get("path") or "")
    if path.is_file():
        return path
    src = Path(catalog.get("source_folder") or "")
    return src / item["file"]


def _write_media_map(catalog_path: Path, catalog: Dict[str, Any]) -> Path:
    items = catalog.get("items") or []
    mapping = {
        "catalog": str(catalog_path),
        "c2pa_stripped": True,
        "items": [
            {
                "file": it["file"],
                "fanvue_media_uuid": it.get("fanvue_media_uuid"),
                "fanvue_media_uuid_previous": it.get("fanvue_media_uuid_previous"),
                "level": it.get("level"),
                "score": it.get("score"),
                "price_eur_suggested": it.get("price_eur_suggested"),
                "fanvue_folder": it.get("fanvue_folder"),
                "vault_label": it.get("vault_label"),
                "c2pa_stripped": it.get("c2pa_stripped"),
            }
            for it in items
            if it.get("fanvue_media_uuid")
        ],
    }
    map_path = catalog_path.parent / "fanvue_media_map.json"
    map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return map_path


def _remap_fan_memory(uuid_map: Dict[str, str]) -> int:
    """Replace old media UUIDs in .fan_memory.json. Returns number of fans touched."""
    if not uuid_map:
        return 0
    mem_path = Path(_ROOT) / ".fan_memory.json"
    if not mem_path.is_file():
        return 0
    data = json.loads(mem_path.read_text(encoding="utf-8"))
    touched = 0
    for _fid, mem in data.items():
        if not isinstance(mem, dict):
            continue
        changed = False
        sent: List[str] = list(mem.get("sent_media_uuids") or [])
        new_sent = [uuid_map.get(u, u) for u in sent]
        if new_sent != sent:
            mem["sent_media_uuids"] = new_sent
            changed = True
        last = mem.get("last_ppv_media_uuid")
        if last and last in uuid_map:
            mem["last_ppv_media_uuid"] = uuid_map[last]
            changed = True
        if changed:
            touched += 1
    if touched:
        mem_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return touched


def main() -> None:
    ap = argparse.ArgumentParser(description="Strip C2PA and re-upload vault photos")
    ap.add_argument("catalog", type=str, help="Path to catalog.json")
    ap.add_argument("--limit", type=int, default=0, help="Only process first N items")
    ap.add_argument("--sleep", type=float, default=0.5, help="Pause between uploads")
    ap.add_argument(
        "--keep-old",
        action="store_true",
        help="Do not soft-delete previous Fanvue media UUIDs",
    )
    ap.add_argument(
        "--no-folder",
        action="store_true",
        help="Upload to vault root only",
    )
    args = ap.parse_args()

    catalog_path = Path(args.catalog).expanduser().resolve()
    if not catalog_path.is_file():
        raise SystemExit(f"Catalog not found: {catalog_path}")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog.get("items") or []
    if not items:
        raise SystemExit("Catalog has no items")

    to_process = list(items)
    if args.limit > 0:
        to_process = to_process[: args.limit]

    fv = FanvueConnector()
    me = fv.get_current_user()
    print(f"→ Fanvue user: @{me.get('handle') or me.get('username') or me.get('uuid')}")
    print(f"→ Catalog: {catalog_path} ({len(to_process)}/{len(items)} to re-upload)\n")

    if not args.no_folder:
        levels = sorted({int(it.get("level") or 0) for it in to_process if it.get("level")})
        for lvl in levels:
            folders = _level_folders()
            name = folders.get(lvl, f"{_VAULT_PREFIX_TITLE}_L{lvl}_misc")
            fv.ensure_vault_folder(name)
            print(f"  folder ready: {name}")
        print()

    order_index = {it["file"]: i for i, it in enumerate(items, 1)}
    uuid_map: Dict[str, str] = {}
    ok = 0
    failed = 0

    for n, item in enumerate(to_process, 1):
        path = _resolve_path(catalog, item)
        if not path.is_file():
            print(f"[{n}/{len(to_process)}] ❌ missing: {item.get('file')}")
            failed += 1
            continue

        old_uuid = item.get("fanvue_media_uuid")
        c2pa = has_c2pa(path)
        idx = order_index.get(item["file"], n)
        # Always derive name/folder from current level (catalog may be stale).
        name = _display_name(idx, item)
        folder = None if args.no_folder else _folder_for(item)
        # Keep captions short — long Grok blurbs are unnecessary for vault.
        caption = (item.get("vault_label") or item.get("file") or "")[:200]
        price_cents = _price_cents(item)
        item["fanvue_name"] = name
        item["fanvue_folder"] = folder

        print(
            f"[{n}/{len(to_process)}] {path.name} c2pa={c2pa} "
            f"old={old_uuid or 'none'} → strip+upload ...",
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
                strip_ai_metadata=True,
            )
        except Exception as e:
            print(f"  ❌ upload {type(e).__name__}: {e}")
            item["fanvue_reupload_error"] = str(e)
            catalog_path.write_text(
                json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            failed += 1
            continue

        new_uuid = result["mediaUuid"]
        if old_uuid and old_uuid != new_uuid:
            uuid_map[old_uuid] = new_uuid
            item["fanvue_media_uuid_previous"] = old_uuid
            if not args.keep_old:
                try:
                    fv.delete_media(old_uuid)
                    print(f"  🗑 deleted old {old_uuid}")
                except Exception as e:
                    print(f"  ⚠ delete old failed: {type(e).__name__}: {e}")

        item["fanvue_media_uuid"] = new_uuid
        item["fanvue_status"] = result.get("status")
        item["fanvue_folder"] = result.get("folder")
        item["fanvue_name"] = result.get("name") or name
        item["c2pa_stripped"] = bool(result.get("stripped"))
        item.pop("fanvue_reupload_error", None)
        ok += 1
        print(
            f"  ✓ new={new_uuid} stripped={result.get('stripped')} "
            f"status={result.get('status')}"
        )

        catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        cards_dir = catalog_path.parent / "cards"
        card_path = cards_dir / f"{Path(item['file']).stem}.json"
        if card_path.is_file():
            try:
                card = json.loads(card_path.read_text(encoding="utf-8"))
                if old_uuid:
                    card["fanvue_media_uuid_previous"] = old_uuid
                card["fanvue_media_uuid"] = new_uuid
                card["fanvue_folder"] = result.get("folder")
                card["c2pa_stripped"] = bool(result.get("stripped"))
                card_path.write_text(
                    json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

        if args.sleep > 0:
            time.sleep(args.sleep)

    map_path = _write_media_map(catalog_path, catalog)
    fans = _remap_fan_memory(uuid_map)

    print(f"\n✅ done. reuploaded={ok} failed={failed} uuid_remaps={len(uuid_map)}")
    print(f"✅ catalog: {catalog_path}")
    print(f"✅ media map: {map_path}")
    if fans:
        print(f"✅ fan_memory remapped for {fans} fan(s)")


if __name__ == "__main__":
    main()
