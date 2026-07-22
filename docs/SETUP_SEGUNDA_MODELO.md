# Segunda cuenta Fanvue (otra modelo)

El bot **ya soporta varias cuentas** en la misma infra (Postgres + Redis). Cada proceso `poll_inbox.py` usa un `ACCOUNT_ID` distinto. No hace falta duplicar el repo entero — solo persona, OAuth, fotos PPV y un segundo poller.

## Qué se comparte vs qué cambia

| Compartido (mismo proyecto) | Por modelo |
|-----------------------------|------------|
| `DEEPSEEK_*`, `XAI_*` (visión) | `ACCOUNT_ID` |
| `FANVUE_CLIENT_ID` / `SECRET` (misma app OAuth) | OAuth token (creator distinto) |
| `DATABASE_URL`, `REDIS_URL` | `personas/<id>.md` |
| Código del bot (`poll_inbox`, gates, router) | `data/<id>_fanvue_media_map.json` + vault en Fanvue |
| | `ELEVENLABS_VOICE_ID` (notas de voz — puede ser la misma que Emma) |

## Checklist rápido

1. **Scaffold** — persona + fila en DB + ruta del vault map  
2. **OAuth** — login como la nueva creadora  
3. **PPV** — rankear fotos → subir al vault Fanvue → sync a Postgres  
4. **Deploy** — segundo servicio poller con env distinto  
5. **Smoke test** — DM de prueba + un PPV  

---

## 1. Crear la persona y la cuenta en DB

```bash
python scripts/setup_new_model.py sofia \
  --handle im.sofiacarter \
  --name "Sofia Reyes" \
  --age 22 \
  --from "Miami, FL" \
  --body "petite, toned, sun-kissed" \
  --vibe "Party girl de Miami — bratty, ruidosa, le encanta la atención"
```

Esto genera:

- `personas/sofia.md` — edítala: ejemplos de chat en su voz, matices, pet names  
- `data/sofia_fanvue_media_map.json` — vacío hasta subir fotos  
- Fila en `accounts` con `account_id=sofia`

**Reglas de persona:** copia las mecánicas duras de `personas/emma.md` (LOCK/SELL, sin video customs, sin `caro/papi/nena/nene`). Cambia nombre, edad, origen, tono y ejemplos.

La persona se carga automáticamente si existe `personas/{ACCOUNT_ID}.md`. Opcional: `PERSONA_FILE=personas/sofia.md`.

---

## 2. OAuth (cuenta Fanvue de la nueva modelo)

Misma app de Fanvue Builder; **inicia sesión como la creadora nueva**:

```bash
export ACCOUNT_ID=sofia
export FANVUE_CREATOR_HANDLE=im.sofiacarter
python scripts/oauth_login.py
```

El token queda en `oauth_tokens` keyed por `account_id=sofia`.

> En local, `.fanvue_tokens.json` es un espejo — siempre exporta `ACCOUNT_ID` antes del OAuth para no pisar el token de Emma.

---

## 3. Fotos PPV (vault)

### 3a. Rankear fotos locales

```bash
python scripts/rank_vault_photos.py /ruta/a/fotos/sofia --copy-ordered
```

Salida: `exports/vault_rank_YYYYMMDD_HHMMSS/` con `catalog.json`.

### 3b. Subir al vault Fanvue

```bash
export ACCOUNT_ID=sofia
export VAULT_FOLDER_PREFIX=Sofia   # carpetas Sofia_L1_lingerie, etc.

python scripts/upload_vault_batch.py exports/vault_rank_*/catalog.json
```

### 3c. Guardar mapa y sincronizar a Postgres

```bash
cp exports/vault_rank_*/fanvue_media_map.json data/sofia_fanvue_media_map.json

export ACCOUNT_ID=sofia
export FANVUE_MEDIA_MAP=data/sofia_fanvue_media_map.json
python scripts/sync_vault_to_pg.py
```

**Importante:** cada poller debe tener su `FANVUE_MEDIA_MAP`. Si no, al arrancar puede cargar el catálogo de Emma por defecto.

---

## 4. Segundo poller (producción)

### Railway (recomendado)

Duplica el servicio **poller** con otro bloque de variables:

| Variable | Valor ejemplo |
|----------|----------------|
| `ACCOUNT_ID` | `sofia` |
| `FANVUE_MEDIA_MAP` | `data/sofia_fanvue_media_map.json` |
| `FANVUE_CREATOR_HANDLE` | `im.sofiacarter` |
| `ELEVENLABS_VOICE_ID` | misma que Emma si queréis (omitir = default) |
| `DATABASE_URL` | mismo Postgres |
| `REDIS_URL` | mismo Redis |
| `FANVUE_CLIENT_ID` / `SECRET` | mismos (si misma app OAuth) |

Opcional: `PERSONA_FILE=personas/sofia.md` (redundante si el archivo existe).

Logs esperados:

```text
storage: Postgres + Redis (account=sofia)
persona: loaded from sofia.md (…)
```

### Docker Compose (local)

Copia el servicio `poller` con otro `container_name` y `ACCOUNT_ID` / `FANVUE_MEDIA_MAP`.

---

## 5. Pruebas

```bash
export ACCOUNT_ID=sofia
export PERSONA_FILE=personas/sofia.md
python scripts/test_chat_flow.py
```

En Fanvue: manda un DM a la nueva creadora y comprueba que el PPV adjunta UUIDs del vault de Sofia, no de Emma.

---

## Datos que necesitas antes de empezar

Para rellenar la persona y el deploy:

1. **account_id** corto (ej. `sofia`) — sin espacios  
2. **Nombre completo** y **edad**  
3. **De dónde es** (ciudad/país)  
4. **Vibe** — 2-3 frases de personalidad  
5. **Handle Fanvue** (ej. `im.sofiacarter`)  
6. **Carpeta de fotos** para PPV  
7. **Voice ID ElevenLabs** (si usáis notas de voz)  

---

## FAQ

**¿Duplico el repo?** No. Un repo, N pollers con `ACCOUNT_ID` distinto.

**¿Otra app OAuth en Fanvue?** No necesariamente. Una app puede autorizar varias creadoras; cada una su token en `oauth_tokens`.

**¿Los fans de Emma y Sofia se mezclan?** No. `fan_memory`, `vault_media`, locks Redis, etc. van keyed por `account_id`.

**¿Packs y lorebook por modelo?** Hoy son globales. La diferencia de personalidad va en `personas/<id>.md`.
