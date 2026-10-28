# Análisis privado de conversaciones reales

`lab.real_chat_analysis` prepara una copia minimizada de una exportación de Fanvue y, en un segundo paso explícito, la envía a OpenRouter para **análisis**. No importa el bot de producción, no llama a Fanvue, no tiene herramientas y no redacta ni envía respuestas. Tampoco entrena ni modifica pesos de modelos o prompts live.

## Entrada y guardado

Acepta el formato `fanvue.chat-export.v1` del importador administrativo de fanv.ai: hasta cinco conversaciones, cien mensajes por conversación y 4 MiB de archivo. Cada mensaje necesita `role` (`fan`, `creator` o `unknown`), `text` (texto o null), `sentAt` (ISO con zona horaria o null) y `hasMedia` (booleano o null). Null en `hasMedia` significa desconocido. Se ignoran otros campos; no se envían enlaces a medios, identificadores originales ni metadatos de cuentas.

Cada mensaje debe ocupar como máximo 16 KiB de texto UTF-8. Este límite se comprueba en toda la exportación antes de seleccionar la ventana; si se supera, reducir el número de mensajes no evita el rechazo. Hay que preparar una selección que excluya ese mensaje, conservando el original privado. El exportador puede guardar textos mayores bajo su límite global; el analizador nunca los recorta silenciosamente.

Por defecto selecciona hasta tres conversaciones y los últimos cuarenta mensajes de cada una, preservando el orden cronológico recibido. Los recortes quedan marcados. Sustituye los identificadores por referencias locales, convierte fechas absolutas en minutos relativos y aplica reglas para correos, teléfonos, URLs, handles, UUIDs, patrones de secretos y nombres facilitados por el operador.

**Es minimización heurística, no anonimización garantizada.** Puede omitir identificadores escritos de otras maneras y sustituir números que no sean teléfonos. Hay que revisar la copia y los nombres antes de enviarla. No se guarda el diccionario que relaciona originales con sustituciones. La copia aún contiene conversaciones privadas.

Los archivos nuevos usan permisos `0600` y directorios nuevos `0700`. No se sobrescriben archivos. Dentro del repositorio sólo se acepta `lab/.data/private-real-chats/`, que ya queda excluido por Git; también se admite una ubicación privada fuera del repositorio. El terminal sólo muestra estado, recuentos, rutas y costes, nunca los mensajes. No añadir originales, copias ni resultados a una PR.

## Dos pasos

Ejecutar desde la raíz del repositorio con el entorno del laboratorio:

```bash
.venv/bin/python -m lab.real_chat_analysis --prepare-only \
  --input /ruta/privada/fanvue-export.json \
  --redact-name NombreDelCliente --redact-name NombreDeLaCreadora \
  --output lab/.data/private-real-chats/muestra-preparada.json
```

Este paso no accede a la clave ni a la red. Si la copia supera 64 KiB de contenido para el modelo, reducir `--max-chats` o `--messages-per-chat`; no se corta texto silenciosamente. Los nombres pasados como argumentos pueden quedar en el historial de la shell: usar una sesión privada o preparar con `prepare_sample(..., names=[...])` desde un proceso que no registre esos argumentos.

Después de revisar la copia:

```bash
.venv/bin/python -m lab.real_chat_analysis --analyze \
  --input lab/.data/private-real-chats/muestra-preparada.json \
  --output lab/.data/private-real-chats/analisis.json
```

`--analyze` acepta sólo una copia `fanvue.chat-analysis-input.v1`. Lee `OPENROUTER_API_KEY` del entorno o de la configuración local existente `.env.lab`, sin cambiarla. La exportación original nunca se envía. La opción `--redact-name` se utiliza exclusivamente en preparación.

El modelo inicial es `deepseek/deepseek-v4.1-flash-1017`, fijado al endpoint `deepinfra/fp8` y con ZDR obligatorio. Para pedir dos análisis independientes:

```bash
.venv/bin/python -m lab.real_chat_analysis --analyze \
  --input lab/.data/private-real-chats/muestra-preparada.json \
  --models deepseek/deepseek-v4.1-flash-1017 x-ai/grok-4.7
```

Grok queda fijado a `xai/zdr`. Si cualquiera de esos endpoints no cumple la política exigida o no admite el formato JSON, la llamada falla. No se amplía la lista de proveedores ni se relaja ZDR para rescatar una respuesta.

## Controles de inferencia

- Máximo dos peticiones, una por modelo solicitado, sin reintentos ni fallback. Se detiene tras un error o un coste no informado.
- Sólo `https://openrouter.ai/api/v1/chat/completions`, sin redirects, herramientas, plugins ni URLs procedentes del chat.
- Utiliza la configuración de proxy HTTPS y certificados del entorno del operador cuando existe; la dirección de destino sigue fijada a OpenRouter. Esto permite ejecutarlo en entornos con salida de red administrada.
- `provider.only`, `allow_fallbacks: false`, `require_parameters: true`, `data_collection: "deny"` y `zdr: true` en cada llamada.
- `X-OpenRouter-Cache: false` para desactivar la caché de respuestas de OpenRouter.
- Tiempo de espera de 45 segundos, conexión de 15; máximo 2.500 tokens de salida y respuesta de 128 KiB.
- Tarifas máximas de enrutamiento: 5 USD/millón de tokens de entrada, 25 USD/millón de salida y cero tarifa fija por petición. Son **topes**, no los precios actuales de los modelos.
- Presupuesto estimado por ejecución de 0,50 USD, ajustable con `--max-estimated-cost-usd` hasta 2 USD. Se calcula conservadoramente con bytes de entrada y margen; **no es una garantía contable ni sustituye un límite de gasto en OpenRouter**. Se conserva el coste informado y su ausencia se marca expresamente.

ZDR del endpoint y la caché no controlan por sí solos los ajustes de registro y uso de entradas/salidas de la cuenta de OpenRouter. Revisar que sus opciones de logging/uso de contenido estén desactivadas. La herramienta no accede a esos ajustes y no promete ausencia absoluta de retención legal, de seguridad o de metadatos.

## Qué produce

El resultado `fanvue.chat-analysis-result.v1` contiene observaciones no gráficas sobre tono, continuidad, ritmo, aceptación o rechazo comercial explícito y límites expresados. Cada observación debe citar IDs existentes de la copia; el validador rechaza referencias inventadas, campos de borradores y salidas de herramientas. El modelo trata el texto histórico como datos no confiables, no como instrucciones.

No se infieren compras, pagos o entregas a partir de mensajes o adjuntos, ni se elaboran perfiles sensibles o estrategias basadas en vulnerabilidades. Los resultados quedan etiquetados `unreviewed_analysis`: el esquema valida forma y referencias, **no demuestra la verdad de cada observación**. Analizar los mismos chats con dos modelos tampoco permite afirmar cuál respondería mejor; para eso hará falta una evaluación aparte, sin enviar respuestas a los fans.

La autorización de los clientes para este uso no sustituye los requisitos aplicables de Fanvue y de los proveedores. La [API Policy de Fanvue](https://legal.fanvue.com/api-policy) contempla integraciones externas de IA, pero su §5.2.13 exige autorizaciones expresas para entrenar, afinar o desarrollar modelos con los datos. No afirma una excepción general para crear conjuntos de evaluación offline. Esta utilidad no representa una aprobación de Fanvue.

## Verificación local

```bash
.venv/bin/python -m pytest tests/test_real_chat_analysis.py -q
```

Las pruebas sólo usan mensajes sintéticos no explícitos y `httpx.MockTransport`. Cubren minimización y datos ausentes, límites, rutas de salida privadas, exclusión de metadatos, ZDR/caché/enrutamiento, presupuesto, fallos sin reintentos, referencias inventadas y formatos de respuesta prohibidos. No consumen créditos ni necesitan claves reales.

Documentación consultada el 28-10-2026: [enrutamiento y max_price](https://openrouter.ai/docs/guides/routing/provider-selection), [caché de respuestas](https://openrouter.ai/docs/guides/features/response-caching), [ZDR](https://openrouter.ai/docs/guides/features/zdr).
