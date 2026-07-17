"""Redis helpers — processed message sets + poller lock."""
from __future__ import annotations

from typing import Optional, Set

import redis

from db import account_id, redis_url

_client: Optional[redis.Redis] = None

PROCESSED_MAX = 2000
PROCESSED_TTL_SECONDS = 7 * 24 * 3600
LOCK_TTL_SECONDS = 45


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(redis_url(), decode_responses=True)
    return _client


def ping() -> bool:
    return bool(get_redis().ping())


def _processed_key(aid: Optional[str] = None) -> str:
    return f"processed:{(aid or account_id())}"


def processed_load(aid: Optional[str] = None) -> Set[str]:
    r = get_redis()
    return set(r.smembers(_processed_key(aid)) or [])


def processed_add(msg_uuid: str, aid: Optional[str] = None) -> None:
    r = get_redis()
    key = _processed_key(aid)
    r.sadd(key, msg_uuid)
    r.expire(key, PROCESSED_TTL_SECONDS)
    # Cap set size (approximate): if too large, wipe oldest by recreating — keep simple
    if r.scard(key) > PROCESSED_MAX:
        # Drop random excess — fine for dedup window
        extra = r.scard(key) - PROCESSED_MAX
        for _ in range(min(extra, 200)):
            r.spop(key)


def processed_remove(msg_uuid: str, aid: Optional[str] = None) -> None:
    r = get_redis()
    r.srem(_processed_key(aid), msg_uuid)


def processed_contains(msg_uuid: str, aid: Optional[str] = None) -> bool:
    return bool(get_redis().sismember(_processed_key(aid), msg_uuid))


def processed_save_set(uuids: Set[str], aid: Optional[str] = None) -> None:
    """Bulk replace (used by migrate / file→redis bootstrap)."""
    r = get_redis()
    key = _processed_key(aid)
    pipe = r.pipeline()
    pipe.delete(key)
    if uuids:
        pipe.sadd(key, *list(uuids)[-PROCESSED_MAX:])
        pipe.expire(key, PROCESSED_TTL_SECONDS)
    pipe.execute()


def acquire_poller_lock(aid: Optional[str] = None, ttl: int = LOCK_TTL_SECONDS) -> bool:
    """SET NX lock so only one poller replica runs per account."""
    key = f"lock:poller:{(aid or account_id())}"
    return bool(get_redis().set(key, "1", nx=True, ex=ttl))


def refresh_poller_lock(aid: Optional[str] = None, ttl: int = LOCK_TTL_SECONDS) -> None:
    key = f"lock:poller:{(aid or account_id())}"
    get_redis().expire(key, ttl)


def release_poller_lock(aid: Optional[str] = None) -> None:
    key = f"lock:poller:{(aid or account_id())}"
    get_redis().delete(key)
