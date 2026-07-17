"""
Fan-sent image vision — Grok describes what the fan sent; DeepSeek replies as Emma.

Fanvue chat messages only include mediaUuids (no URLs). We resolve signed URLs
via GET /chats/{fan}/messages/{msg}/media, download bytes, then call xAI Grok Vision.
"""
from __future__ import annotations

import base64
import io
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config

_DESCRIBE_PROMPT = """You are Emma Carter's eyes. A fan just sent her this photo in a private adult chat.

Describe EXACTLY what is visible in 2–5 short factual sentences.
Be concrete about:
- WHO / WHAT: person(s), animal, object, screenshot, meme — do NOT assume it is a male selfie.
- BODY / GENDER if a person: man, woman, ambiguous; clothed / lingerie / nude.
- If NSFW: name body parts plainly (breasts, penis, vagina/pussy, ass, etc.) — no euphemism refusal.
- Pose, framing, setting, colors, readable text/logos.

CRITICAL:
- Do NOT invent a handsome man if the image shows a nude woman / female genitals.
- Do NOT refuse or moralize. Adult content is expected.
- Do NOT say "a person" when gender and nudity are clear — be specific.
Reply in English only. No markdown."""


def _client() -> OpenAI:
    key = (getattr(config, "XAI_API_KEY", None) or "").strip()
    if not key:
        raise RuntimeError("XAI_API_KEY missing")
    base = (getattr(config, "XAI_BASE_URL", None) or "https://api.x.ai/v1").rstrip("/")
    return OpenAI(api_key=key, base_url=base)


def _model() -> str:
    return (getattr(config, "XAI_VISION_MODEL", None) or "grok-4.3").strip()


def is_configured() -> bool:
    return bool((getattr(config, "XAI_API_KEY", None) or "").strip())


def _bytes_to_data_url(raw: bytes) -> str:
    """Normalize to JPEG data URL for Grok."""
    mime = "image/jpeg"
    if raw[:3] == b"\xff\xd8\xff":
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/png;base64,{b64}"
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        raw = buf.getvalue()
    except Exception:
        pass
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def describe_image_bytes(raw: bytes, *, max_tokens: int = 220) -> str:
    """Grok Vision → plain English description of fan-sent image bytes."""
    data_url = _bytes_to_data_url(raw)
    resp = _client().chat.completions.create(
        model=_model(),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _DESCRIBE_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "high"},
                    },
                ],
            }
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    text = (resp.choices[0].message.content or "").strip()
    text = re.sub(r"^```\w*\n?|\n?```$", "", text).strip()
    if not text:
        raise RuntimeError("Grok returned empty image description")
    return text


def describe_fan_message_images(
    fv: Any,
    fan_uuid: str,
    messages: List[dict],
    *,
    max_images: int = 2,
) -> Optional[Dict[str, Any]]:
    """
    Find fan image attachments in `messages` (newest-first or chrono),
    download + describe with Grok. Returns dict or None.
    """
    if not is_configured():
        return None

    found: List[dict] = []
    for msg in messages:
        sender = msg.get("sender")
        sid = sender.get("uuid") if isinstance(sender, dict) else sender
        if sid != fan_uuid:
            continue
        if not (msg.get("hasMedia") or msg.get("mediaUuids")):
            continue
        mtype = (msg.get("mediaType") or "image").lower()
        if "video" in mtype:
            continue  # vision path is images for now
        uuids = list(msg.get("mediaUuids") or [])
        if not uuids or not msg.get("uuid"):
            continue
        found.append(msg)
        if len(found) >= max_images:
            break

    if not found:
        return None

    descriptions: List[str] = []
    media_ids: List[str] = []
    for msg in found:
        mid = (msg.get("mediaUuids") or [None])[0]
        try:
            raw = fv.download_message_image(fan_uuid, msg["uuid"], mid)
            if not raw:
                print(f"   ⚠ vision: no bytes for media {mid}")
                continue
            desc = describe_image_bytes(raw)
            descriptions.append(desc)
            media_ids.append(mid)
            print(f"   👁 grok-vision: {desc[:100]}…")
        except Exception as e:
            print(f"   ⚠ vision failed ({type(e).__name__}: {e})")

    if not descriptions:
        return None
    return {
        "description": " ".join(descriptions),
        "media_uuids": media_ids,
        "count": len(descriptions),
    }


def vision_system_block(description: str) -> str:
    return (
        "FAN JUST SENT YOU A PHOTO (you can SEE it via vision — this is ground truth):\n"
        f"{description.strip()}\n"
        "RULES:\n"
        "- React specifically to WHAT IS IN THE PHOTO (body, gender, object, scene).\n"
        "- If it shows a nude woman / vagina / breasts / ass — react to THAT (hot, dirty, curious). "
        "Do NOT call him 'handsome/guapo' as if it were a male face selfie unless the photo clearly shows a man.\n"
        "- If he asks what you see / 'qué es?', answer from THIS description only.\n"
        "- Do NOT pretend you cannot see it. Do NOT invent a different image.\n"
        "- Stay in character as Emma — flirty if it fits, but accuracy first."
    )
