"""Processed message UUID set — Redis when available, else JSON file."""
from __future__ import annotations

import json
import os
from typing import Optional, Set

from db import account_id, use_postgres, use_redis

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILE = os.path.join(_ROOT, ".processed_messages.json")


def _file_load() -> Set[str]:
    if not os.path.exists(_FILE):
        return set()
    try:
        with open(_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _file_save(processed: Set[str]) -> None:
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(processed)[-500:], f)


def load(aid: Optional[str] = None) -> Set[str]:
    aid = aid or account_id()
    if use_redis():
        from db import redis_client

        try:
            return redis_client.processed_load(aid)
        except Exception:
            if use_postgres():
                raise
            return _file_load()
    return _file_load()


def save(processed: Set[str], aid: Optional[str] = None) -> None:
    aid = aid or account_id()
    _file_save(processed)  # mirror
    if use_redis():
        from db import redis_client

        redis_client.processed_save_set(processed, aid)


def add(msg_uuid: str, processed: Optional[Set[str]] = None, aid: Optional[str] = None) -> Set[str]:
    aid = aid or account_id()
    if processed is None:
        processed = load(aid)
    processed.add(msg_uuid)
    if use_redis():
        from db import redis_client

        redis_client.processed_add(msg_uuid, aid)
        _file_save(processed)
    else:
        _file_save(processed)
    return processed
