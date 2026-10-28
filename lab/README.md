# Laboratorio de conversación

Aplicación local en español para probar conversaciones sintéticas, comparar hasta cuatro modelos de OpenRouter y valorar sus respuestas con nombres ocultos. Es un proceso independiente: no lee conversaciones reales, no utiliza el almacén del poller y no envía mensajes ni cobra en Fanvue.

## Arranque

Python 3.10 o posterior. Desde la raíz del repositorio:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-lab.txt
cp lab/.env.example .env.lab
# Edita .env.lab y configura OPENROUTER_API_KEY.
.venv/bin/python -m lab
```

En Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lab.txt
Copy-Item lab\.env.example .env.lab
notepad .env.lab
.\.venv\Scripts\python.exe -m lab
```

Si `.env.lab` ya existe, conserva su contenido: no lo sobrescribas con el ejemplo. Abre `http://127.0.0.1:8765` en el mismo equipo. Puedes cambiar el puerto con `--port 8766`. El lanzador escucha únicamente en loopback; esta versión es una herramienta local, no un servicio público multiusuario.

La clave se carga en el servidor desde `.env.lab`, ignorado por Git. Nunca se envía al navegador ni se incluye en las exportaciones. No reutilices `.env` de producción para arrancar el laboratorio. Los datos se guardan en `lab/.data/lab.sqlite3`, también ignorado. `LAB_DATABASE_PATH` permite elegir otra ruta aislada.

## Recorrido

1. Selecciona un caso. Cada caso abre una sesión independiente con fan, mensajes, memoria y catálogo ficticios.
2. Selecciona hasta cuatro modelos, incluidos varios del mismo proveedor OpenRouter.
3. Genera alternativas A/B/C/D. Cada alternativa usa el mismo snapshot; no cambia la memoria ni crea una oferta por generarse.
4. Valora naturalidad, pertinencia, continuidad y criterio comercial de 1 a 5. Escribe una observación breve. Revela los modelos después de valorar.
5. Edita y aprueba solo un candidato para continuar la conversación. Escribe el siguiente mensaje como fan.
6. Inspecciona memoria, decisión y contexto. Una corrección conserva el mensaje de origen. Una baja comercial persiste; una compra solo cambia mediante un evento explícito.
7. Exporta las respuestas, trazas y valoraciones. La exportación revela nombres de modelos, incluso si permanecían ocultos en pantalla.

El modo **Prueba funcional · sin IA** responde únicamente a los casos iniciales con textos preparados. No interpreta mensajes libres, no tiene tokens/coste y no admite puntuaciones de calidad. Un error de OpenRouter nunca se convierte en un ejemplo preparado.

## Casos y memoria

Los doce casos cubren charla casual, ritmo breve, recuerdo, corrección de nombre, idioma, precio, objeción, pausa temporal, baja persistente, compra, petición no disponible e identidad de IA. Son conversaciones no gráficas de personajes adultos ficticios.

Las reglas de `policy.py` son deliberadamente limitadas: reconocen algunas declaraciones explícitas en español e inglés. No son un extractor universal de preferencias. La ficha conserva hechos con procedencia; el estado comercial guarda ofertas, compras y archivos adquiridos por separado. No infiere una compra de lo que diga un usuario.

Una oferta se habilita a partir del producto y la petición; el modelo redacta su presentación. Los precios y compras se verifican en código. Las comprobaciones de texto detectan algunos precios y afirmaciones incorrectos, pero no prueban todas las afirmaciones posibles. La revisión de borradores sigue siendo necesaria.

## Comparación reproducible

El catálogo inicial guarda IDs, fecha, precios publicados, capacidades y endpoints de ocho candidatos comprobados. Puedes actualizar el catálogo público desde la interfaz. La disponibilidad final depende de la cuenta y del proveedor.

Cada modelo conserva un endpoint de ejecución concreto. Se registra el tag pedido, la cuantización y el proveedor que OpenRouter declara como seleccionado. Se desactivan cambios de modelo y fallbacks de proveedor. Una ruta agotada o incompatible permanece como error; no se cambia por otra en silencio.

Los ajustes efectivos se guardan por respuesta. El límite de salida es 1.024 tokens; se pide razonamiento bajo solo cuando el endpoint lo declara compatible. Una salida truncada o incompleta queda identificada y no se puede aprobar. `usage.cost` se conserva cuando existe; ausencia de coste no equivale a coste cero.

Los informes muestran valoraciones humanas y su tamaño de muestra. Los resultados funcionales no entran en las medias. No se calculan puntuaciones de calidad automáticas ni se atribuye conversión a ventas simuladas. Un lote pequeño sirve para seleccionar candidatos para otra ronda, no para demostrar superioridad comercial.

## Ejecutar un lote desde terminal

```bash
.venv/bin/python -m lab.evaluate --list
.venv/bin/python -m lab.evaluate --live --cases casual price \
  --models x-ai/grok-4.7 deepseek/deepseek-v4.1-flash-1017 qwen/qwen3.8-27b
```

`--live` habilita solicitudes reales que pueden consumir saldo. Máximo cuatro modelos y 48 respuestas por ejecución. Usa `--repetitions 2` para repetir casos y `--output lab/.data/my-round.json` para elegir la exportación. El comando no puntúa: guarda resultados para su revisión. La interfaz permite también crear lotes y abrir sus sesiones.

Sin `--models`, se comparan **DeepSeek V4.1 Flash 1017 y Grok 4.7**. El operador eligió una respuesta de DeepSeek como referencia de tono juguetón; esa preferencia sobre un ejemplo no equivale a una evaluación comercial completa. El prompt de laboratorio conserva la versión que produjo esa respuesta: una variante posterior de estilo se probó en 24 respuestas y se descartó al no demostrar una mejora clara. El detalle del experimento está en `docs/briefs/conversation_lab.md`.

Para continuar cada modelo con los mismos seis mensajes de prueba, conservando sus propias respuestas anteriores:

```bash
.venv/bin/python -m lab.evaluate --live --dialogue \
  --output lab/.data/dialogue-new-round.json
```

El guion aprueba los borradores sintéticos mediante `reviewer=test_harness`; eso permite continuar el diálogo y no crea valoraciones humanas. Una respuesta incompleta o bloqueada por el validador detiene esa conversación. En una ronda, esa comprobación produjo un falso positivo sobre una reafirmación negativa de compra; la corrección conserva las advertencias originales y la interfaz las reevalúa con una versión identificable.

## Relación con el motor actual

El laboratorio reutiliza `core.prompt_layers` y su presupuesto, pero usa una persona de prueba breve y almacenamiento propio. Su redacción se normaliza solo en los espacios exteriores; no se aplica el sanitizador histórico. La traza identifica esta diferencia para no confundir una comparación de modelos con una prueba del comportamiento actual del poller.

El motor existente incorpora un `TurnTrace` opcional para diagnosticar su recorrido real sin alterar sus llamadas predeterminadas:

```python
from core.turn_trace import TurnTrace
from core.reply_engine import generate_emma_reply

trace = TurnTrace(capture_messages=True)
text, decision = generate_emma_reply("Mensaje ficticio", trace=trace)
record = trace.as_dict()
```

Ese ejemplo usa las dependencias y configuración del motor existente, incluido su proveedor. Úsalo únicamente en un entorno aislado con datos sintéticos. La traza no escribe archivos ni registra conversaciones automáticamente; el llamador decide si conservarla. El tamaño original de la persona solo se declara cuando el llamador proporciona el texto exacto mediante `inspect_core`.

## Verificación

```bash
.venv/bin/python -m pytest tests/test_lab_contracts.py tests/test_lab_providers.py -q
# Con requirements.txt instalado:
.venv/bin/python -m pytest tests/test_turn_trace.py -q
```

Estas pruebas no llaman modelos de pago. Comprueban aislamiento, memoria corregida, bajas, duplicados, control humano, revisiones obsoletas, snapshots idénticos, contratos HTTP, atribución de proveedores y errores sin secretos.

## Fuentes de integración

- Catálogo: https://openrouter.ai/api/v1/models
- Rutas: https://openrouter.ai/docs/guides/routing/provider-selection
- Chat: https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion
- Metadatos: https://openrouter.ai/docs/guides/features/router-metadata
- Uso y coste: https://openrouter.ai/docs/cookbook/administration/usage-accounting

Las condiciones aplicables del router y de cada proveedor siguen siendo relevantes. Estas pruebas sintéticas no sustituyen la revisión de permisos para usar conversaciones reales ni una integración final con Fanvue.
