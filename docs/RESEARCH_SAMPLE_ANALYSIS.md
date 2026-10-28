# Importar una muestra de investigación con evidencia de compras

`lab.research_sample` conecta el export `fanvue.research-sample.v1` de la aplicación con el transporte de análisis privado del laboratorio. El recorrido es **vincular cuenta y archivo → comprobar elegibilidad → minimizar → revisar contenido → analizar**. El export antiguo `fanvue.chat-export.v1` conserva su CLI y su contrato; no se debe renombrar un schema para convertirlo.

Este módulo permite observación no gráfica de calidad conversacional, preferencias expresas, límites y resultados comerciales registrados. No genera respuestas para fans, no crea ejemplos de fine-tuning, no modifica prompts del bot y no llama a Fanvue. Preparar y registrar la revisión son operaciones locales; solo `--analyze` puede llamar a OpenRouter.

## 1. Conservar el original y acreditar la cuenta

Guardar la descarga sin editar en un directorio privado, por ejemplo `lab/.data/private-real-chats/example-import/original.json`. Guardar también el manifiesto privado descrito en `docs/RESEARCH_COHORT.md`. Todos los nombres e identificadores de esta guía son ficticios.

El manifiesto debe identificar la cuenta seleccionada, su procedencia real verificada, actividad y evidencia de ingresos positivos. La mera conexión, una frase comercial, una intención de compra o `account_001` no acreditan ingresos ni identifican al propietario de la descarga. Sin evidencia, conservar `pending_evidence`; no convertir la ausencia en cero. Si la evidencia es este mismo export, registrar la ruta, su hash de bytes y un localizador como `earnings.verifiedWindowFanNetUsdCents`, el importe observado y el período exacto.

Las exclusiones privadas por cuenta, conexión o handle tienen precedencia sobre clasificación e ingresos. Una clasificación `test` en otra conexión de la misma cuenta también la excluye. Si un rango del manifiesto tiene `review: "excluded"` y el hash del mismo archivo, se bloquea ese archivo entero antes de abrir su texto. La primera importación puede tener `conversations: []`; no hay que inventar fechas de mensajes desconocidas para completar ese campo.

Registrar las autorizaciones ya existentes para `analysis` y `evaluation` y su fundamento; una declaración del propietario puede documentarse como tal. La preparación técnica del contenido no solicita de nuevo autorización al usuario. Los hashes comprueban integridad; no certifican origen, veracidad económica ni alcance de permisos.

## 2. Crear la vinculación privada

El export usa pseudónimos locales que se reinician en cada descarga. Hace falta asociar **la cuenta realmente seleccionada en la aplicación** con el archivo exacto. La vinculación es una declaración privada del operador, no una identidad deducida del chat.

Crear `binding.json` con este contrato:

```json
{
  "schemaVersion": "fanvue.research-binding.v1",
  "sourceFile": "original.json",
  "sourceSha256": "HASH_SHA256_DE_LOS_BYTES_DEL_ORIGINAL",
  "manifestFile": "manifest.json",
  "manifestSha256": "HASH_SHA256_DE_LOS_BYTES_DEL_MANIFIESTO",
  "accountKey": "local-account-alias",
  "analysisPurpose": "pattern_discovery"
}
```

Ambos hashes son 64 caracteres hexadecimales minúsculos. Las rutas son relativas al directorio de `binding.json`, sin `..` ni enlaces simbólicos. El campo `accountKey` debe identificar una única entrada del manifiesto.

Este ejemplo genera los hashes sin decodificar conversaciones y escribe un archivo nuevo con permisos privados. Ejecutarlo desde la raíz del repositorio después de registrar la cuenta y la evidencia en el manifiesto:

```bash
.venv/bin/python - <<'PY'
import hashlib
from pathlib import Path
from lab.research_cohort import write_private

directory = Path("lab/.data/private-real-chats/example-import")
def sha256(path):
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

write_private(directory / "binding.json", {
    "schemaVersion": "fanvue.research-binding.v1",
    "sourceFile": "original.json",
    "sourceSha256": sha256(directory / "original.json"),
    "manifestFile": "manifest.json",
    "manifestSha256": sha256(directory / "manifest.json"),
    "accountKey": "local-account-alias",
    "analysisPurpose": "pattern_discovery",
})
PY
```

El gate del CLI comprueba el manifiesto, las exclusiones, actividad, procedencia, ingresos y acción autorizada antes de abrir el original o el preparado. Solo hashea la evidencia de la cuenta seleccionada. El hash y el parseo de cada JSON vinculado usan los mismos bytes; se rechaza un archivo sustituido o modificado.

Usar `split.unit: "account"` con semilla fijada antes de estudiar los resultados. `pattern_discovery` solo admite la partición `development`; `heldout_evaluation` solo admite `holdout` y su prompt exige aplicar únicamente categorías descriptivas fijas, sin descubrir patrones ni proponer cambios de estrategia. Esta segunda acción **no es un benchmark predictivo**; la salida del modelo aún requiere revisión. No cambiar la semilla para conseguir una partición deseada. Una modificación del manifiesto invalida las vinculaciones anteriores y requiere volver a prepararlas/revisarlas.

## 3. Minimizar sin perder evidencia

```bash
.venv/bin/python -m lab.research_sample --prepare \
  --binding lab/.data/private-real-chats/example-import/binding.json \
  --output lab/.data/private-real-chats/example-import/prepared.json
```

Se puede añadir `--redact-name "Nombre Ficticio"`. Para elegir explícitamente un subconjunto, añadir uno o más `--conversation-id chat_002`. No hay recorte silencioso a 40 mensajes: conserva hasta los 50 mensajes de cada conversación seleccionada, sus IDs originales, orden, truncación, rol, tipo, estado y atribución conocida. Si el payload supera 64 KiB, la operación falla antes de enviar nada; seleccionar menos conversaciones. Si una sola conversación todavía supera el límite, obtener otra descarga con menos mensajes desde el exportador, conservar el original anterior y crear la vinculación de la nueva descarga.

La copia usa `fanvue.research-analysis-input.v1`. Conserva:

- Eventos de compra y ajustes `refund`, `chargeback` y `earningsDeduction`, con importes enteros en centavos USD y sus signos. La suma neta debe coincidir con el neto ajustado de la compra. Una liberación positiva de una deducción no se convierte en reembolso negativo.
- `eventId`, `messageId`, `reversesEventId` y el estado exacto del enlace, dentro de cada conversación. `event_001` y `message_001` pueden repetirse en otros chats.
- Tiempos de mensajes y eventos relativos a la compra: negativos antes, positivos después, `null` desconocido. Se señala el orden irregular o la presencia de fechas desconocidas; no se reordena ni se inventa historia.
- La evidencia agregada de ingresos positivos y la duración de la ventana completa, con máximo de 31 días. El original vinculado conserva las fechas absolutas y todos sus agregados para auditoría privada.
- Selección por compras positivas, contexto reciente/truncado, mensajes posteriores al pago y límites fijos del análisis.

No se transmiten la identidad privada de la cuenta, rutas, hashes, fechas absolutas ni metadatos libres del export. El texto se minimiza por heurísticas; **no se garantiza anonimato**. Los campos arbitrarios de `limitations` del original tampoco se copian al prompt.

## 4. Revisar la copia minimizada

Inspeccionar `prepared.json` localmente, retirar identificadores residuales y excluir o suprimir material explícito. Se permite editar **solo el texto** durante esta revisión; usar una marca neutral de omisión cuando corresponda, sin redactar respuestas ni reconstruir contenido íntimo. Para excluir una conversación de la selección, volver a preparar otra copia con `--conversation-id`. No editar eventos, importes, fechas relativas, enlaces, selección ni partición.

Después de esa revisión técnica completada:

```bash
.venv/bin/python -m lab.research_sample --review-non-explicit \
  --binding lab/.data/private-real-chats/example-import/binding.json \
  --input lab/.data/private-real-chats/example-import/prepared.json \
  --output lab/.data/private-real-chats/example-import/reviewed.json
```

El comando registra la revisión y el digest del payload exacto; no es un clasificador automático de contenido explícito. Compara todos los hechos estructurados con el original vinculado. Un cambio posterior del payload invalida la revisión, aunque sea un solo carácter. Cada artefacto se escribe como archivo nuevo, con permisos `0600`; no se sobrescriben originales ni revisiones.

## 5. Analizar con el transporte existente

Este es el único paso con envío externo, cuando ya se dispone de una copia revisada:

```bash
.venv/bin/python -m lab.research_sample --analyze \
  --binding lab/.data/private-real-chats/example-import/binding.json \
  --input lab/.data/private-real-chats/example-import/reviewed.json \
  --output lab/.data/private-real-chats/example-import/analysis.json \
  --models deepseek/deepseek-v4.1-flash-1017 \
  --max-estimated-cost-usd 0.50
```

La clave se obtiene del entorno o `.env.lab`, después de todos los gates. Se mantienen los modelos/rutas ya permitidos, ZDR, `data_collection=deny`, caché desactivada, límites de tamaño/coste/tiempo y ausencia de reintentos o fallbacks. Como máximo se pueden seleccionar dos modelos existentes. Una copia nueva sin binding o sin revisión falla también por la API Python antes de construir el cliente HTTP; el CLI antiguo no es una vía alternativa para el schema nuevo.

El prompt específico reconoce los eventos verificados. Exige citar `conversationId` y los `messageIds`/`eventIds` existentes en ese chat. La salida sigue marcada `unreviewed_analysis`; validar el formato y las referencias no demuestra que una interpretación del modelo sea correcta. Revisar sus conclusiones antes de usarlas.

Pagos registrados no equivalen a retiradas, entrega, causalidad ni autoría humana. `pendingBalance` continúa pendiente; `hasMedia: null` continúa desconocido; `authoredByHuman` siempre es `null`. El contexto posterior a la compra permanece etiquetado para observación descriptiva: este flujo no lo transforma en una evaluación de predicción sin filtraciones. La selección de compradores positivos no permite calcular conversión, comparar modelos por calidad de respuesta ni deducir qué texto produjo una venta.

## Verificación local

```bash
.venv/bin/python -m pytest tests/test_research_sample.py \
  tests/test_real_chat_analysis.py tests/test_research_cohort.py -q
```

Todos los datos de estas pruebas son sintéticos y el transporte HTTP está simulado. Cubren exclusiones antes de abrir textos/evidencia, particiones, hashes, revisión antes de cliente/credenciales, invariantes del export, ajustes con signo, citas dentro de su chat y compatibilidad del flujo antiguo. No se usan clientes, claves, modelos ni chats reales.
