"""ElevenLabs text-to-speech — sensual voice notes for Emma (Eleven v3 + audio tags)."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import config

_RETRY = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(requests.exceptions.RequestException),
)

_EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F600-\U0001F64F]+",
    flags=re.UNICODE,
)


def is_configured() -> bool:
    return bool((getattr(config, "ELEVENLABS_API_KEY", "") or "").strip())


def _clean_script(text: str) -> str:
    """Strip emojis; keep [audio tags] for v3."""
    s = _EMOJI.sub("", text or "").strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s


@_RETRY
def synthesize_to_file(
    text: str,
    *,
    voice_id: Optional[str] = None,
    language_code: Optional[str] = None,
    out_path: Optional[Path] = None,
) -> Path:
    """
    Generate MP3 via ElevenLabs REST API (eleven_v3 + inline [audio tags]).
    Returns path to the audio file (caller deletes when done).
    """
    api_key = (getattr(config, "ELEVENLABS_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    vid = (voice_id or getattr(config, "ELEVENLABS_VOICE_ID", "") or "").strip()
    if not vid:
        raise RuntimeError("ELEVENLABS_VOICE_ID not set")

    script = _clean_script(text)
    if not script:
        raise ValueError("empty voice script")
    max_c = int(getattr(config, "VOICE_NOTE_MAX_CHARS", 320) or 320)
    if len(script) > max_c:
        script = script[:max_c].rsplit(" ", 1)[0]

    model = getattr(config, "ELEVENLABS_MODEL", "eleven_v3") or "eleven_v3"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    payload: dict = {
        "text": script,
        "model_id": model,
        "voice_settings": {
            "stability": float(getattr(config, "ELEVENLABS_STABILITY", 0.35)),
            "similarity_boost": float(getattr(config, "ELEVENLABS_SIMILARITY", 0.78)),
            "style": float(getattr(config, "ELEVENLABS_STYLE", 0.50)),
            "speed": float(getattr(config, "ELEVENLABS_SPEED", 0.93)),
            "use_speaker_boost": True,
        },
        "apply_text_normalization": "off",
    }
    lang = (language_code or "").strip().lower()
    if lang and model.startswith("eleven_v3"):
        payload["language_code"] = lang

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    resp = requests.post(
        url,
        json=payload,
        headers=headers,
        params={"output_format": "mp3_44100_128"},
        timeout=int(getattr(config, "ELEVENLABS_TIMEOUT_SEC", 90) or 90),
    )
    if not resp.ok:
        detail = (resp.text or "")[:400]
        raise requests.HTTPError(
            f"ElevenLabs {resp.status_code}: {detail}",
            response=resp,
        )

    if out_path is None:
        fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="emma_voice_")
        out_path = Path(tmp)
        import os

        os.close(fd)
    else:
        out_path = Path(out_path)

    out_path.write_bytes(resp.content)
    if out_path.stat().st_size < 500:
        raise RuntimeError("ElevenLabs returned empty or tiny audio")
    return out_path
