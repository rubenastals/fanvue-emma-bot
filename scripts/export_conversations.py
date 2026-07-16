"""Export Fanvue chats to exports/ as JSON + readable TXT."""
import json
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from api.fanvue_connector import FanvueConnector


def main():
    fv = FanvueConnector()
    me = fv.get_current_user()
    chats = fv.list_chats(size=20)
    os.makedirs("exports", exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    out = {
        "exported_at": stamp,
        "creator": {
            "uuid": me.get("uuid"),
            "handle": me.get("handle"),
            "displayName": me.get("displayName"),
        },
        "chats": [],
    }

    for c in chats:
        u = c.get("user") or {}
        fan_uuid = u.get("uuid")
        msgs = fv.get_messages(fan_uuid, size=50) if fan_uuid else []
        msgs_chrono = list(reversed(msgs))
        thread = []
        for m in msgs_chrono:
            s = m.get("sender")
            if isinstance(s, dict):
                sid, sh = s.get("uuid"), s.get("handle")
            else:
                sid, sh = s, None
            who = "emma" if sid == me.get("uuid") else "fan"
            thread.append(
                {
                    "uuid": m.get("uuid"),
                    "who": who,
                    "sender_handle": sh,
                    "text": m.get("text"),
                    "hasMedia": m.get("hasMedia"),
                    "price": m.get("price"),
                    "sentAt": m.get("sentAt") or m.get("createdAt"),
                }
            )
        out["chats"].append(
            {
                "fan": u,
                "isRead": c.get("isRead"),
                "unreadMessagesCount": c.get("unreadMessagesCount"),
                "lastMessageAt": c.get("lastMessageAt"),
                "messages": thread,
            }
        )

    path_json = os.path.join("exports", f"conversation_{stamp}.json")
    path_txt = os.path.join("exports", f"conversation_{stamp}.txt")

    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    with open(path_txt, "w", encoding="utf-8") as f:
        f.write(f"Emma @{me.get('handle')} — export {stamp}\n")
        f.write("=" * 60 + "\n")
        for chat in out["chats"]:
            fan = chat["fan"]
            f.write(
                f"\n### Chat with @{fan.get('handle')} ({fan.get('displayName')})\n"
            )
            f.write(f"fan_uuid={fan.get('uuid')}\n\n")
            for m in chat["messages"]:
                tag = "EMMA" if m["who"] == "emma" else "FAN "
                t = (m.get("text") or "").replace("\n", " ")
                media = " [MEDIA]" if m.get("hasMedia") else ""
                price = f" [price={m.get('price')}]" if m.get("price") else ""
                f.write(f"{tag} | {m.get('sentAt')}: {t}{media}{price}\n")

    total_msgs = sum(len(c["messages"]) for c in out["chats"])
    print(path_json)
    print(path_txt)
    print(f"chats={len(out['chats'])} messages={total_msgs}")


if __name__ == "__main__":
    main()
