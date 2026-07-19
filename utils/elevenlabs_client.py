"""ElevenLabs text-to-speech — sensual voice notes for Emma."""
from __future__ import annotations

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


def is_configured() -> bool:
    return bool((getattr(config, "ELEVENLABS_API_KEY", "") or "").strip())


@_RETRY
def synthesize_to_file(
    text: str,
    *,
    voice_id: Optional[str] = None,
    out_path: Optional[Path] = None,
) -> Path:
    """
    Generate MP3 via ElevenLabs REST API.
    Returns path to the audio file (caller deletes when done).
    """
    api_key = (getattr(config, "ELEVENLABS_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    vid = (voice_id or getattr(config, "ELEVENLABS_VOICE_ID", "") or "").strip()
    if not vid:
        raise RuntimeError("ELEVENLABS_VOICE_ID not set")

    script = (text or "").strip()
    if not script:
        raise ValueError("empty voice script")
    if len(script) > int(getattr(config, "VOICE_NOTE_MAX_CHARS", 120) or 120):
        script = script[: int(getattr(config, "VOICE_NOTE_MAX_CHARS", 120))].rsplit(" ", 1)[0]

    model = getattr(config, "ELEVENLABS_MODEL", "eleven_multilingual_v2") or "eleven_multilingual_v2"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    payload = {
        "text": script,
        "model_id": model,
        "voice_settings": {
            "stability": float(getattr(config, "ELEVENLABS_STABILITY", 0.38)),
            "similarity_boost": float(getattr(config, "ELEVENLABS_SIMILARITY", 0.82)),
            "style": float(getattr(config, "ELEVENLABS_STYLE", 0.42)),
            "use_speaker_boost": True,
        },
    }
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    resp = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=int(getattr(config, "ELEVENLABS_TIMEOUT_SEC", 45) or 45),
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
