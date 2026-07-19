"""Debug: show what history DeepSeek sees for a fan chat."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

from api.fanvue_connector import FanvueConnector
from config import config
from core.reply_engine import filter_messages_for_context, fanvue_messages_to_turns

fv = FanvueConnector()
me = fv.get_current_user()
creator = me["uuid"]
chats = fv.list_chats(size=10)
for c in chats:
    u = c.get("user") or {}
    handle = u.get("handle") or ""
    fan_uuid = u.get("uuid")
    if not fan_uuid:
        continue
    msgs = fv.get_messages(fan_uuid, size=100)
    ctx = filter_messages_for_context(
        msgs,
        hours=int(config.HISTORY_HOURS),
        max_messages=int(config.HISTORY_MAX_MESSAGES),
        min_messages=int(config.HISTORY_MIN_MESSAGES),
    )
    turns = fanvue_messages_to_turns(
        ctx, fan_uuid, creator, max_messages=int(config.HISTORY_MAX_MESSAGES)
    )
    print(f"\n=== @{handle} turns={len(turns)} ctx_msgs={len(ctx)} ===")
    for t in turns[-8:]:
        role = t["role"][:4]
        body = (t["content"] or "").replace("\n", " | ")[:120]
        print(f"  {role}: {body}")
