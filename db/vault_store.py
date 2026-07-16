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


def _default_map_path() -> Optional[Path]:
    env = (os.getenv("FANVUE_MEDIA_MAP") or "").strip()
    if env:
        p = Path(env)
        return p if p.is_file() else None
    maps = sorted(
        glob(str(_ROOT / "exports" / "vault_rank_*" / "fanvue_media_map.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    return Path(maps[0]) if maps else None


def _items_from_file() -> List[Dict[str, Any]]:
    path = _default_map_path()
    if not path:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = []
    for it in data.get("items") or []:
        uid = it.get("fanvue_media_uuid")
        if not uid:
            continue
        items.append(
            {
                "file": it.get("file"),
                "media_uuid": uid,
                "level": int(it.get("level") or 1),
                "score": int(it.get("score") or 1),
                "price": float(it.get("price_eur_suggested") or 4),
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
                    "level": int(r["level"] or 1),
                    "score": int(r["score"] or 1),
                    "price": float(r["price"] or 4),
                    "folder": r["folder"],
                    "label": r["label"] or r["file_name"] or "photo",
                }
                for r in rows
            ]
    return _items_from_file()


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
                    "level": int(it.get("level") or 1),
                    "score": int(it.get("score") or 1),
                    "price": float(it.get("price") or it.get("price_eur_suggested") or 4),
                    "folder": it.get("folder") or it.get("fanvue_folder"),
                    "label": it.get("label") or it.get("vault_label") or "photo",
                    "ver": catalog_version,
                },
            )
            n += 1
    return n
