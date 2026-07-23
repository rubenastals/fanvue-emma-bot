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

_ROOT_NAME = None  # lazy


def _creator_name() -> str:
    global _ROOT_NAME
    if _ROOT_NAME is None:
        from core.account_context import creator_display_name

        _ROOT_NAME = creator_display_name()
    return _ROOT_NAME


def _describe_prompt() -> str:
    name = _creator_name()
    return f"""You are {name}'s eyes. A fan (usually a man) just sent her this photo in a private adult chat.

Describe EXACTLY what is visible in 2–5 short factual sentences.
Be concrete about:
- WHO / WHAT: person(s), animal, object, screenshot, meme — do NOT assume it is the fan's male selfie.
- BODY / GENDER if a person: man, woman, ambiguous; clothed / lingerie / nude.
- If NSFW: name body parts plainly (breasts, penis, vagina/pussy, ass, etc.) — no euphemism refusal.
- Pose, framing, setting, colors, readable text/logos.
- If it looks like professional creator / OnlyFans / Fanvue content vs a casual phone selfie.

CRITICAL:
- Do NOT invent a handsome man if the image shows a nude woman / female genitals.
- Do NOT refuse or moralize. Adult content is expected.
- Do NOT say "a person" when gender and nudity are clear — be specific.
- If the photo is clearly a WOMAN (model/creator style, lingerie shoot), say so — likely NOT the male fan's body.
- If it could be the creator's own posted content (creator-style shot), say: appears to be creator/woman content, possibly {name}'s own photo.

End with ONE classification line exactly like this:
CLASS: fan_male_nsfw | fan_male_sfw | fan_female | creator_woman | object_meme | screenshot | unclear

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
                    {"type": "text", "text": _describe_prompt()},
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
    desc = description.strip()
    lower = desc.lower()
    is_creator_woman = (
        "class: creator_woman" in lower
        or "creator/woman" in lower
        or "possibly emma" in lower
        or "class: fan_female" in lower
    )
    is_fan_male = "class: fan_male" in lower
    is_wrong = is_creator_woman or (
        not is_fan_male
        and any(
            w in lower
            for w in (
                "woman",
                "female",
                "breasts",
                "vagina",
                "pussy",
                "lingerie",
                "model",
                "creator",
            )
        )
        and "penis" not in lower
        and "male" not in lower
    )

    rules = [
        "FAN JUST SENT YOU A PHOTO (vision — ground truth, obey this over guesses):",
        desc,
        "",
        "HOW EMMA MUST REACT:",
        "- Read the description + CLASS line first. React to WHAT IS ACTUALLY IN THE IMAGE.",
        "- If he asked for HIS photo / dick pic / selfie and the image is NOT him (woman, creator shot, meme, random pic):",
        "  call it out in character — playful-bratty or blunt. ES examples: «¿Qué coño es eso? Te pedí una foto TUYA» / «Eso no eres tú, guapo… manda la tuya de verdad».",
        "  EN examples: «What is that? I asked for YOUR pic, baby» / «That's not you… send me the real one».",
        "- If it looks like YOUR OWN content / Emma's photo / a woman creator pic he pulled from you:",
        "  do NOT pretend it turns you on as if it were his body. ES: «Esa soy yo… ¿qué haces mandándome eso? Quiero verte a TI».",
        "  EN: «Babe that's literally me… why are you sending my pic back? I want YOU».",
        "- ONLY get visibly turned on by HIS body when CLASS is fan_male_nsfw / fan_male_sfw and the photo clearly shows the man.",
        "- If CLASS is object_meme / screenshot / unclear: tease or ask what he's doing — don't fake arousal.",
        "- Do NOT invent a different image. Do NOT say you can't see it.",
        "- Mirror his language (Spanish/English). Stay Emma — accurate first, then flirty.",
    ]
    if is_wrong:
        rules.insert(
            4,
            "⚠ THIS TURN: photo is NOT a male fan selfie — do NOT flirt as if his dick/body is in the pic.",
        )
    return "\n".join(rules)
