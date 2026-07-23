"""Vault media catalog — Postgres or fanvue_media_map.json."""
from __future__ import annotations

import json
import os
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from db import account_id, use_postgres

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ACCOUNT = "emma"


def _default_map_path(aid: Optional[str] = None) -> Optional[Path]:
    aid = (aid or account_id()).strip().lower()
    env = (os.getenv("FANVUE_MEDIA_MAP") or "").strip()
    if env:
        p = Path(env)
        return p if p.is_file() else None
    # Per-account map before Emma default
    if aid and aid != _DEFAULT_ACCOUNT:
        per_account = _ROOT / "data" / f"{aid}_fanvue_media_map.json"
        if per_account.is_file():
            return per_account
    shipped = _ROOT / "data" / "fanvue_media_map.json"
    if shipped.is_file():
        return shipped
    maps = sorted(
        glob(str(_ROOT / "exports" / "vault_rank_*" / "fanvue_media_map.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    return Path(maps[0]) if maps else None


def validate_map_for_account(raw: dict, aid: Optional[str] = None) -> Optional[str]:
    """Return error string if JSON account_id disagrees with running account."""
    aid = aid or account_id()
    map_aid = (raw.get("account_id") or "").strip().lower()
    if map_aid and map_aid != aid.lower():
        return f"media map account_id={map_aid!r} != ACCOUNT_ID={aid!r}"
    return None


def _items_from_file(aid: Optional[str] = None) -> List[Dict[str, Any]]:
    path = _default_map_path(aid)
    if not path:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    err = validate_map_for_account(data, aid)
    if err:
        print(f"   WARNING: vault map skipped — {err} ({path.name})")
        return []
    items = []
    for it in data.get("items") or []:
        uid = it.get("fanvue_media_uuid")
        if not uid:
            continue
        level_raw = it.get("level")
        score_raw = it.get("score")
        price_raw = it.get("price_eur_suggested")
        if price_raw is None:
            price_raw = it.get("price")
        items.append(
            {
                "file": it.get("file"),
                "media_uuid": uid,
                "media_uuid_previous": it.get("fanvue_media_uuid_previous") or None,
                "level": int(level_raw) if level_raw is not None else 1,
                "score": int(score_raw) if score_raw is not None else 1,
                "price": float(price_raw) if price_raw is not None else 4.0,
                "folder": it.get("fanvue_folder"),
                "label": it.get("vault_label") or it.get("file") or "photo",
            }
        )
    return items


def load_items(aid: Optional[str] = None) -> List[Dict[str, Any]]:
    aid = aid or account_id()
    if use_postgres():
        from db.pg import session_scope

        with session_scope() as session:
            rows = session.execute(
                text(
                    """
                    SELECT media_uuid, file_name, level, score, price, folder, label
                    FROM vault_media WHERE account_id = :aid
                    ORDER BY level ASC, price ASC
                    """
                ),
                {"aid": aid},
            ).mappings().all()
        if rows:
            return [
                {
                    "file": r["file_name"],
                    "media_uuid": r["media_uuid"],
                    "level": int(r["level"]) if r["level"] is not None else 1,
                    "score": int(r["score"]) if r["score"] is not None else 1,
                    "price": float(r["price"]) if r["price"] is not None else 4.0,
                    "folder": r["folder"],
                    "label": r["label"] or r["file_name"] or "photo",
                }
                for r in rows
            ]
        # Postgres on + empty vault for this account — do NOT fall back to Emma file
        return []
    return _items_from_file(aid)


def replace_items(
    items: List[Dict[str, Any]],
    *,
    aid: Optional[str] = None,
    catalog_version: str = "",
) -> int:
    aid = aid or account_id()
    if not use_postgres():
        return 0
    from db.pg import session_scope
    from db.schema import ensure_account

    ensure_account(aid)
    with session_scope() as session:
        session.execute(
            text("DELETE FROM vault_media WHERE account_id = :aid"),
            {"aid": aid},
        )
        n = 0
        for it in items:
            uid = it.get("media_uuid") or it.get("fanvue_media_uuid")
            if not uid:
                continue
            session.execute(
                text(
                    """
                    INSERT INTO vault_media
                        (account_id, media_uuid, file_name, level, score, price, folder, label, catalog_version)
                    VALUES
                        (:aid, :uid, :file, :level, :score, :price, :folder, :label, :ver)
                    """
                ),
                {
                    "aid": aid,
                    "uid": uid,
                    "file": it.get("file") or it.get("file_name"),
                    "level": int(it["level"]) if it.get("level") is not None else 1,
                    "score": int(it["score"]) if it.get("score") is not None else 1,
                    "price": float(
                        it["price"]
                        if it.get("price") is not None
                        else (
                            it["price_eur_suggested"]
                            if it.get("price_eur_suggested") is not None
                            else 4
                        )
                    ),
                    "folder": it.get("folder") or it.get("fanvue_folder"),
                    "label": it.get("label") or it.get("vault_label") or "photo",
                    "ver": catalog_version,
                },
            )
            n += 1
    return n
