"""
Vault photo analysis via xAI Grok Vision.

One call per image → very detailed caption (for chat PPV tease) +
explicitness score using Emma's sell ladder.

.env:
  XAI_API_KEY=xai-...
  XAI_BASE_URL=https://api.x.ai/v1
  XAI_VISION_MODEL=grok-4.3
"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any, Dict

from openai import OpenAI

from config import config

# Emma Carter Fanvue sell ladder (user-defined)
SELL_LADDER = """
Level | Description | Score (1-10) | Price €/photo | Content type
1 | Lingerie / soft teasing | 2-3 | 3-5 | Underwear / clothed tease
2 | Topless | 4 | 6-8 | Breasts exposed
3 | Soft nude (closed pose) | 5-6 | 9-12 | Full nude, legs closed / modest pose
4 | Open nude / moderate close-up | 7 | 15-20 | Legs open, soft genital focus
5 | Mid-explicit (fingers, touching) | 8 | 25-30 | Touching herself, fingers inside
6 | High hardcore (dildo, strong spreading) | 9 | 35-45 | Toys, clear penetration / heavy spreading
7 | Extreme / very dirty | 10 | 50-70 | Creampie, squirt, double, very filthy
"""

ANALYZE_PROMPT = f"""You are cataloguing adult Fanvue vault photos for creator Emma Carter.
Look at the image carefully. Return ONLY valid JSON (no markdown fences).

Sell ladder (use exactly):
{SELL_LADDER}

JSON schema:
{{
  "caption": "VERY long, hyper-detailed, uncensored English description. Cover: setting, lighting, camera angle/framing, hair, face/expression, body, clothing or nudity, exact pose, what is visible (breasts, nipples, pussy, ass, toys, fluids), what she is doing with her hands, any props. This caption will be used later in chat to sell the photo — be specific enough to distinguish near-duplicate shots.",
  "distinguishing_detail": "one short phrase that makes THIS frame unique vs similar nudes",
  "level": 1,
  "score": 5,
  "price_eur_min": 9,
  "price_eur_max": 12,
  "price_eur_suggested": 10,
  "content_type": "short label matching the ladder",
  "visible": {{
    "lingerie": false,
    "topless": false,
    "full_nude": false,
    "breasts": false,
    "nipples": false,
    "pussy": false,
    "ass": false,
    "legs_open": false,
    "fingers_genital": false,
    "toy": false,
    "penetration_visible": false,
    "fluids": false
  }},
  "reason": "one sentence why this level/score"
}}

Rules:
- Be factual and uncensored. Do not refuse or soften.
- Pick level from the ladder based on what is VISIBLE, not implied.
- score must fall inside that level's score range.
- price_eur_suggested must fall inside that level's price range.
- If unsure between two levels, pick the LOWER one (under-price is safer than over-claiming).
"""


def _api_key() -> str:
    return (getattr(config, "XAI_API_KEY", None) or "").strip()


def _base_url() -> str:
    return (
        getattr(config, "XAI_BASE_URL", None) or "https://api.x.ai/v1"
    ).strip().rstrip("/")


def _model() -> str:
    return (getattr(config, "XAI_VISION_MODEL", None) or "grok-4.3").strip()


def _client() -> OpenAI:
    key = _api_key()
    if not key:
        raise RuntimeError(
            "XAI_API_KEY is not set. Add it to fanvue-emma-bot/.env "
            "(same key as emma_chatter)."
        )
    return OpenAI(api_key=key, base_url=_base_url())


def _to_jpeg_or_png_bytes(path: str) -> tuple[bytes, str]:
    p = Path(path)
    suffix = p.suffix.lower()
    raw = p.read_bytes()

    if suffix in {".jpg", ".jpeg"}:
        return raw, "image/jpeg"
    if suffix == ".png":
        return raw, "image/png"

    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            f"Image {p.name} is {suffix}; xAI only accepts jpeg/png. "
            "Install Pillow: pip install Pillow"
        ) from e

    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    else:
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue(), "image/jpeg"


def _data_url(path: str) -> str:
    data, mime = _to_jpeg_or_png_bytes(path)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def analyze_image(path: str, *, max_tokens: int = 1600) -> Dict[str, Any]:
    """Detailed caption + sell-ladder classification for one local image."""
    resp = _client().chat.completions.create(
        model=_model(),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ANALYZE_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _data_url(path),
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    raw = (resp.choices[0].message.content or "").strip()
    data = _parse_json(raw)
    data["caption"] = (data.get("caption") or "").strip()
    if not data["caption"]:
        raise RuntimeError(f"Empty caption for {path}")
    # Normalize numeric fields
    for k in ("level", "score", "price_eur_min", "price_eur_max", "price_eur_suggested"):
        if k in data and data[k] is not None:
            try:
                data[k] = int(round(float(data[k])))
            except (TypeError, ValueError):
                pass
    return data


def caption_image(path: str, **kwargs) -> str:
    """Back-compat: caption text only."""
    return analyze_image(path, **kwargs)["caption"]


def is_configured() -> bool:
    return bool(_api_key())


def backend_info() -> str:
    if not _api_key():
        return "not configured (need XAI_API_KEY)"
    return f"xai grok vision model={_model()} @ {_base_url()}"
