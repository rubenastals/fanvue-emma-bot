# Cómo dar acceso al agente (ejecutar Fanvue, DB, Birbo…)

## Resumen rápido

| Dónde trabajas | Qué hacer |
|----------------|-----------|
| **Cursor en tu PC** | `.env` en la raíz del repo + hook (ya incluido) |
| **Cloud Agent** | Secretos en [Cursor Dashboard → Cloud Agents → Environments](https://cursor.com/dashboard/cloud-agents) |

El `.env` **nunca** va a GitHub. El agente solo lo ve si está en tu máquina o en Dashboard Secrets.

---

## A) Cursor local (tu PC) — recomendado

### 1. Abre la carpeta correcta

`File → Open Folder` → donde está el bot **con** `.env` (el mismo que usa Emma).

Comprueba:

```powershell
dir .env
```

### 2. Copia el `.env` si hace falta

Mismo archivo que Emma: `FANVUE_CLIENT_ID`, `FANVUE_CLIENT_SECRET`, `DATABASE_URL`, `REDIS_URL`, `DEEPSEEK_API_KEY`, etc.

Para Sophia añade en el **servicio/poller** (no hace falta duplicar todo el `.env` local si alternas):

```env
ACCOUNT_ID=sophia
FANVUE_MEDIA_MAP=data/sophia_fanvue_media_map.json
```

### 3. Hook automático (este repo)

Ya está en `.cursor/hooks.json`: antes de cada comando shell carga `.env`.

Reinicia Cursor después de `git pull` si no lo tenías.

### 4. Verificar que el agente ve credenciales

Pide al agente:

```text
ejecuta: python scripts/verify_sophia_setup.py
```

Si sale `FANVUE_CLIENT_ID ✅` y `Fanvue API: @...` → listo.

---

## B) Cloud Agent (agente en la nube)

Tu PC puede estar en local, pero si el chat es **Cloud**, el agente corre en un VM **sin** tu `.env`.

### 1. Dashboard

1. [cursor.com/dashboard/cloud-agents](https://cursor.com/dashboard/cloud-agents)
2. **Environments** → entorno de `fanvue-emma-bot`
3. Pestaña **Secrets** → añade como **Runtime Secret**:

| Secret | Ejemplo |
|--------|---------|
| `DATABASE_URL` | URL Postgres Railway |
| `REDIS_URL` | URL Redis Railway |
| `FANVUE_CLIENT_ID` | de Fanvue Builder |
| `FANVUE_CLIENT_SECRET` | de Fanvue Builder |
| `DEEPSEEK_API_KEY` | |
| `XAI_API_KEY` | |
| `ACCOUNT_ID` | `sophia` o `emma` |
| `FANVUE_MEDIA_MAP` | `data/sophia_fanvue_media_map.json` |

4. **Reinicia** el Cloud Agent después de guardar secretos.

### 2. Red

Si el entorno tiene allowlist, permite: Fanvue API, Railway Postgres, DeepSeek, xAI.

### 3. Instalación

`.cursor/environment.json` define `pip install` al arrancar el VM.

---

## C) Qué NO hacer

- No pegues secretos en el chat
- No subas `.env` a GitHub
- No esperes que Cloud lea el `.env` de tu Windows

---

## Comandos que el agente debería poder ejecutar solo

```powershell
git pull
python scripts/inspect_fan.py birbo
python scripts/audit_account_isolation.py
python scripts/verify_sophia_setup.py
python scripts/start_sophia.py
```

Railway redeploy sigue siendo manual o con `railway` CLI en tu PC (necesita login Railway).
