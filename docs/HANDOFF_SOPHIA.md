# Handoff: Sophia Cler (segunda cuenta Fanvue)

**Para el agente en Cursor local:** lee este archivo + `personas/sophia.md`. El usuario (Ruben) quiere seguir aquí sin repetir setup.

## Estado actual (Jul 2026)

| Item | Estado |
|------|--------|
| Rama | `cursor/segunda-cuenta-fanvue-6dbc` (PR #34) |
| `ACCOUNT_ID` | `sophia` |
| Persona | `personas/sophia.md` — Sophia Cler, 19, Miami, **English only** |
| PPV vault | Vacío — `data/sophia_fanvue_media_map.json` (bonding only) |
| ElevenLabs | **Misma voz que Emma** — no cambiar `ELEVENLABS_VOICE_ID` |
| OAuth Sophia | **PENDIENTE** — usuario debe correr `start_sophia.py` local |
| Railway poller #2 | **PENDIENTE** — duplicar servicio con `ACCOUNT_ID=sophia` |

## Lo que el usuario debe hacer (mínimo)

Desde la carpeta del repo con `.env` de Emma:

```powershell
git fetch origin
git checkout cursor/segunda-cuenta-fanvue-6dbc
# o merge PR #34 a main y git pull main

python scripts/start_sophia.py
```

- Browser → login **Sophia Cler** (no Emma) → Authorize → pegar URL si pide.
- Si `.env` tiene `DATABASE_URL` (Railway), token queda en `oauth_tokens` para `account_id=sophia`.

Verificar:

```powershell
$env:ACCOUNT_ID = "sophia"
python scripts/test_fanvue_api.py
```

## Producción Railway (después del OAuth)

Duplicar servicio `poller` con:

```
ACCOUNT_ID=sophia
FANVUE_MEDIA_MAP=data/sophia_fanvue_media_map.json
FANVUE_CREATOR_HANDLE=<handle real de Sophia>
DATABASE_URL / REDIS_URL = mismos que Emma
FANVUE_CLIENT_ID / SECRET = mismos que Emma
# ELEVENLABS_VOICE_ID — omitir (misma que Emma)
```

## Arquitectura (recordatorio)

- **Un repo**, dos pollers, misma Postgres/Redis.
- Datos aislados por `account_id` — no se cruzan fans ni vault si cada poller tiene su `ACCOUNT_ID`.
- Código compartido: fix en `main` actualiza ambos al redeploy.

## Archivos clave tocados en este trabajo

- `personas/sophia.md`
- `data/sophia_fanvue_media_map.json`
- `scripts/start_sophia.py` — equivalente a `start_emma.py`
- `scripts/setup_new_model.py`
- `core/prompt_core.py` — auto-load `personas/{ACCOUNT_ID}.md`
- `docs/SETUP_SEGUNDA_MODELO.md`

## Pendiente del usuario

1. Handle Fanvue exacto de Sophia (si difiere de placeholder).
2. Nombre legal/display si quieren ajustar persona.
3. PPV cuando tengan fotos: `rank_vault_photos` → `upload_vault_batch` con `VAULT_FOLDER_PREFIX=Sophia`.

## Errores que ya tuvo Ruben (Windows)

- Repo no estaba en `C:\Users\ruben\fanvue-emma-bot` — abrir carpeta correcta en Cursor.
- Usó `export` (Linux) en CMD — en PowerShell: `$env:ACCOUNT_ID = "sophia"`.
- No usar placeholders tipo `<DATABASE_URL>` — copiar URL real de Railway.

## Prompt sugerido para agente local

> Continúa el setup de Sophia Cler. Lee `docs/HANDOFF_SOPHIA.md`. Ayúdame a ejecutar `start_sophia.py`, verificar OAuth, y configurar el segundo poller en Railway.
