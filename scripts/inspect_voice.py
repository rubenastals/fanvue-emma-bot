"""Inspect last voice notes: memory, chat captions, ElevenLabs settings."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

from config import config
from core import fan_memory
from api.fanvue_connector import FanvueConnector

Juan = "351076d9-61f1-4ea3-8a24-41230cf174d4"

print("=== ElevenLabs config ===")
print(f"model={config.ELEVENLABS_MODEL}")
print(f"voice_id={config.ELEVENLABS_VOICE_ID}")
print(f"stability={config.ELEVENLABS_STABILITY} style={config.ELEVENLABS_STYLE}")
print(f"similarity={config.ELEVENLABS_SIMILARITY} speed={config.ELEVENLABS_SPEED}")
print(f"min_chars={config.VOICE_NOTE_MIN_CHARS} max_chars={config.VOICE_NOTE_MAX_CHARS}")

mem = fan_memory.get(Juan) or {}
print("\n=== Fan memory (voice) ===")
print(f"sent={mem.get('voice_notes_sent')} today={mem.get('voice_notes_today')}")
print(f"last_at={mem.get('last_voice_at')}")
print(f"last_script={mem.get('last_voice_script')}")

fv = FanvueConnector()
me = fv.get_current_user()
msgs = fv.get_messages(Juan, size=40)
print("\n=== Recent chat (media / Emma) ===")
for msg in reversed(msgs[-25:]):
    s = msg.get("sender")
    sid = s.get("uuid") if isinstance(s, dict) else s
    who = "EMMA" if sid == me.get("uuid") else "FAN"
    t = (msg.get("text") or "").replace("\n", " | ")
    mt = msg.get("mediaType") or ""
    has = bool(msg.get("hasMedia") or msg.get("mediaUuids"))
    if has or who == "EMMA" or "audio" in t.lower():
        ts = (msg.get("sentAt") or msg.get("createdAt") or "")[:19]
        print(f"{ts} {who} type={mt!r} media={has} | {t[:120]}")
