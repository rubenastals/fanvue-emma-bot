# Dataset privado de respuestas revisadas

`lab.chat_dataset` convierte una copia minimizada `fanvue.chat-analysis-input.v1`
y su revisión explícita en dos archivos: ejemplos SFT generales y casos positivos
reservados para evaluación. Todo el proceso es local. No consulta proveedores,
no abre configuración de claves, no entrena pesos, no envía mensajes y no cambia
el bot. Tampoco modifica la cohorte comercial que exige ingresos positivos.

## Procedencia y revisión

Conserva el export original `fanvue.chat-export.v1` y la copia preparada mediante
`lab.real_chat_analysis --prepare-only`. Revisa localmente la minimización y crea
un sidecar privado a partir de `lab/fixtures/chat_dataset_review.example.json`.
La plantilla contiene placeholders, hashes inválidos y un ejemplo `pending`:
no representa aprobación ni datos listos para entrenamiento.

El sidecar requiere:

- Identidad privada de la cuenta y conexión, handle, clasificación `real_customer`
  y fundamento de procedencia. La exclusión de la cuenta de pruebas declarada por
  el propietario está fijada en código mediante huellas SHA-256 de sus tres
  identificadores normalizados y no puede desactivarse desde el archivo. No se
  publican los identificadores literales. Estas huellas son configuración de
  exclusión, no una garantía general de anonimato.
  Se comprueba antes de abrir el original o la copia preparada. Los identificadores
  se normalizan con Unicode NFKC, espacios exteriores y casefold; se retira `@`
  del handle para comparar.
- Base de la autorización ya registrada, persona revisora, fecha con zona horaria
  y alcance `entire_example_privacy_and_non_explicit`. No se vuelve a solicitar
  una autorización que el operador ya haya documentado.
- `rawFile`, relativo al directorio del sidecar, sin `..`, componentes ocultos ni
  symlinks; debe terminar en `.json`. El SHA-256 de sus bytes exactos
  (`rawBytesSha256`) es distinto del hash de su JSON canónico
  (`rawCanonicalSha256`). Este último debe coincidir con `prepared.sourceSha256`.
- `preparedBytesSha256`, calculado **después de terminar la revisión de texto**.
  Cualquier edición posterior invalida la revisión hasta que se revise de nuevo
  y se actualice el digest. No se cambia automáticamente ningún hash.
- Un binding por cada conversación preparada: `id`, `stableKey`, índice de la
  conversación en el original (`sourceConversationIndex`, base cero) y comienzo
  de la ventana de mensajes (`sourceMessageStart`, base cero). En la preparación
  usual del último tramo, el comienzo es cantidad original menos cantidad
  preparada. Se comprueban roles, medios, tiempos relativos, IDs locales,
  truncamiento y orden temporal frente al rango original. La revisión puede
  cambiar texto, pero no estos hechos, ni inventar texto donde el original era
  vacío o sólo contenía medios.

Los hashes comprueban integridad, no identidad remota, consentimiento ni calidad
de las respuestas. Esos datos siguen siendo declaraciones del operador. El lector
general regenera IDs `chat_001`: no sirven como clave estable entre descargas.
Mantén una clave privada consistente para la misma conversación. Si sólo puede
identificarse dentro de un export, limita el estudio a ese bundle y no unas otras
descargas suponiendo que son conversaciones nuevas.

## Aprobar ejemplos completos

Cada entrada tiene `contextMessageIds`, `targetMessageIds`, `status` y
`textOnlySufficient`. Sólo se incluyen entradas `approved_non_explicit`. La persona
revisora debe haber comprobado **toda la ventana**, tanto contexto como objetivo:
privacidad, contenido no explícito, coherencia y aptitud de la respuesta para el
comportamiento deseado. Un target histórico no se considera bueno por su origen.

`textOnlySufficient: true` declara que el texto basta para comprender el ejemplo,
incluidos mensajes que tengan medios o presencia de medios desconocida. No se
abren medios. Los mensajes de roles `unknown`, texto vacío o `null` se rechazan
si aparecen en el ejemplo. La revisión no debe aprobar respuestas que dependan
de una imagen, audio u otro contexto no disponible.

La ventana puede comenzar después del primer mensaje. Debe ser contigua y estar
inmediatamente antes de la respuesta objetivo, sin mensajes futuros, IDs
duplicados ni reordenación. Comienza y termina en un mensaje `fan`. Los targets
son un bloque completo de mensajes consecutivos `creator`; se agrupan sus burbujas
en una respuesta. Los mensajes consecutivos del mismo rol dentro del contexto
también se unen con dos saltos de línea. No se añade un prompt de sistema.

Los ejemplos `pending` y `rejected` no se exportan. Sin ninguna aprobación la
operación falla con `no_approved_examples` y no crea archivos. Una aprobación de
un ejemplo no aprueba otros fragmentos del mismo chat. No hay clasificador
automático que certifique privacidad o contenido no explícito.

Para evaluar fallos observados sin aprender de una respuesta mala, utiliza un
benchmark separado con contexto y rúbrica, sin esa respuesta como target positivo.
Este módulo sólo exporta evaluación de ejemplos positivos aprobados.

## Partición y duplicados

Fija la semilla antes de comparar modelos. Cada clave de conversación se asigna
mediante un hash determinista de semilla, cuenta y clave. Todas sus ventanas van
juntas. Los historiales exactamente duplicados y los contextos exactamente
duplicados, normalizados con NFKC y espacios, unen sus conversaciones en un mismo
grupo **antes** de partir. Los ejemplos completos duplicados se conservan una sola
vez. Reordenar los bindings o ejemplos no cambia las asignaciones.
Dos rangos del mismo `sourceConversationIndex` se agrupan siempre, incluso si el
operador les asignó accidentalmente claves distintas.

El holdout puede quedar vacío con pocas conversaciones o tras agrupar duplicados.
No se cambia la semilla ni se trasladan ejemplos para ocultarlo. La salida tiene
`readiness: insufficient` si falta cualquiera de las particiones y `pilot` si ambas
tienen ejemplos. `readyForTraining` permanece `false`: el módulo no certifica
volumen, calidad, modelo base o protocolo de entrenamiento. Los recuentos permiten
valorar cuán pequeño es el piloto. Una sola cuenta no mide generalización entre
cuentas, y no se atribuyen ventas ni autoría humana a las respuestas.

La comprobación de fugas cubre **este bundle**, no otros exports ni paráfrasis
semánticas. Incorporar nuevos datos o duplicados crea otra versión que debe
revisarse como conjunto. No mezcles salidas independientes sin comprobar identidad,
solapamiento y particiones con un registro acumulado.

## Ejecutar

Desde la raíz del checkout, con las dependencias de `requirements-lab.txt`:

```bash
python -m lab.chat_dataset \
  --prepared /ruta/privada/prepared-revisado.json \
  --review /ruta/privada/review.json \
  --output-dir /ruta/privada/dataset-v1
```

El directorio de salida debe ser nuevo. Dentro del repositorio sólo se admite
`lab/.data/private-real-chats/`. Los directorios nuevos usan `0700` y los archivos
`0600`. Todas las validaciones terminan antes de crear la salida; si una escritura
falla, se elimina el directorio recién creado. Un proceso terminado abruptamente
puede dejar una carpeta incompleta: `manifest.json` se escribe al final y registra
los hashes de ambos JSONL. Nunca reutilizar una salida sin su manifiesto válido.

- `train.jsonl`: una línea `{"messages": [{"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."}], "targetMessageIndex": 1}` por ejemplo.
  El último turno es la única respuesta objetivo. El adaptador de entrenamiento
  debe aplicar pérdida exclusivamente a ese turno y enmascarar las respuestas
  `assistant` anteriores del contexto. No subir este contenedor directamente a
  un servicio suponiendo que interpretará `targetMessageIndex`: los formatos y
  máscaras de cada proveedor requieren adaptación y validación posterior.
- `evaluation.jsonl`: `id`, `inputMessages` y `referenceResponse`. Sólo se entregan
  `inputMessages` al modelo evaluado; `referenceResponse` es la respuesta reservada
  para comparación, nunca contexto de inferencia ni datos de entrenamiento.
- `manifest.json`: hashes, parámetros de split, asignaciones con referencias
  opacas, recuentos de aprobados/rechazados/pendientes/duplicados, limitaciones y
  `trainingJobStarted: false`. No incluye textos, identidad de cuentas ni revisores.

Los JSONL siguen conteniendo conversaciones privadas revisadas. No añadir ninguno
de estos archivos, el sidecar o los originales a Git ni a una PR. Stdout sólo
muestra estado, recuentos y destino; los errores usan códigos fijos sin textos.

## Pruebas sin red

```bash
python -m unittest discover -s tests -p test_chat_dataset.py -v
```

Las pruebas usan cuentas y mensajes sintéticos, directorios temporales y ningún
proveedor. Cubren la exclusión antes de lectura, hashes distintos, aprobación de
todo el ejemplo, orden y roles, hechos de origen, duplicados y particiones,
confidencialidad de salidas y fallos de escritura sin sobrescritura.
