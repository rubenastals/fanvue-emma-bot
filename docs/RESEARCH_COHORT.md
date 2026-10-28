# Cohorte privada de investigación conversacional

`lab.research_cohort` registra **qué fuentes pueden pasar a revisión**, por qué y con qué evidencia. Es una utilidad local de metadatos: no consulta Fanvue, no lee la configuración de proveedores, no envía contenido a modelos, no redacta respuestas y no entrena modelos. No modifica el bot de producción.

Su objetivo es preparar una investigación sobre atención, naturalidad, preferencias expresas y resultados comerciales verificables. No genera un corpus de respuestas sexuales explícitas ni técnicas de presión emocional.

## Elegibilidad y exclusiones

Cada cuenta se clasifica como `test`, `real_verified` o `unknown`. La clasificación y sus motivos los aporta el operador; el programa no decide que un cliente sea real porque tenga una conexión, actividad o ingresos.

La denylist privada admite `accountId`, `connectionId` y `handle`. Cualquiera de esos campos puede activar una exclusión. Los identificadores se normalizan con NFKC, espacios exteriores y casefold; en handles se retira el prefijo `@`. **La exclusión prevalece incluso sobre `real_verified` e ingresos positivos.** Una compra de prueba no convierte una cuenta de prueba en una fuente comercial válida. Una exclusión o clasificación `test` se propaga a otras conexiones del mismo `accountId` presentes en el manifiesto.

No hay nombres, handles ni IDs reales codificados en el módulo o en las pruebas. Mantener la denylist en el manifiesto privado, incluirla en cada nueva captación y conservar los motivos. Una cuenta excluida permanece en el registro de procedencia, pero no se abren sus archivos y no recibe partición de análisis.

| Estado | Significado |
|---|---|
| `eligible` | Cuenta declarada `real_verified`, activa y con evidencia de ingresos positivos cuyo archivo coincide con el hash. Puede pasar a revisión dentro de las autorizaciones registradas. |
| `pending_evidence` | Falta verificar origen real, actividad o ingresos positivos. Los datos ausentes siguen ausentes; no se convierten en cero. |
| `excluded` | Cuenta de pruebas, entrada en denylist o cuenta inactiva. |

`real_verified` necesita una justificación en `classificationBasis`. La validación comprueba estructura e integridad de archivos; **no certifica la veracidad financiera del contenido ni sustituye la revisión de procedencia**. Tampoco demuestra que todos los fans de una cuenta real sean clientes orgánicos: revisar posibles conversaciones de prueba antes de admitir ejemplos concretos.

## Ingresos y compras son evidencias distintas

`revenueEvidence` conserva el tipo de medida (`gross_earnings` o `net_earnings`), importe en unidades menores, moneda, período, cuenta, fecha de verificación, registro de origen y hash del archivo. No se suma automáticamente entre monedas, métricas o períodos. Un importe neto negativo es válido y permanece negativo; no permite admitir una cuenta por ingresos positivos.

La aplicación no impone un período común ni un umbral de actualidad. **Elegir y registrar el mismo período antes de comparar cuentas**, por ejemplo los últimos 30 días completos, y revisar su solapamiento con las conversaciones seleccionadas. Conectar recientemente una cuenta no demuestra haber cobrado recientemente. Ingresos brutos tampoco son beneficio.

Una cuenta con ingresos no demuestra que una conversación haya vendido un PPV. `purchaseEvidence` exige un evento verificable de compra o reembolso, con ID, cuenta, conversación, moneda, importe, fecha y archivo de respaldo. El programa rechaza atribuciones a otra cuenta/conversación y eventos duplicados del mismo tipo. Conserva compras y reembolsos por separado; no transforma automáticamente un pago en una venta neta exitosa ni atribuye causalidad a un mensaje.

Sin eventos, `commercialOutcome` queda `unknown`. No significa rechazo, venta perdida ni cero compras. Para estudiar fracasos, hacen falta una ventana de observación y un registro suficientemente completo de resultados; la ausencia de un evento en una exportación parcial no basta.

## Acciones independientes

La autorización para usar una fuente y su calidad estadística son cuestiones distintas. `authorizations` registra por separado `analysis`, `evaluation` y `training`, con valores `authorized`, `denied` o `not_recorded` y una base documental breve.

- `analysisReadiness=ready_for_review` requiere cuenta elegible, conversación no excluida y autorización de análisis registrada.
- `evaluationReadiness=ready_for_review` añade autorización de evaluación y revisión `approved_non_explicit` de la conversación.
- `trainingReadiness` siempre es `unsupported`; `trainingExportAllowed` siempre es `false`, incluso si el operador registra autorización de entrenamiento.

Estos estados no son una certificación legal ni una aprobación automática de cada uso. La [API Policy de Fanvue, §5.2.13](https://legal.fanvue.com/api-policy) exige autorización expresa de Fanvue y de los usuarios para entrenar, afinar o desarrollar modelos con esos datos. Una declaración de consentimiento de clientes no prueba la autorización de Fanvue. No se presenta el uso de prompts, recuperación de ejemplos o evaluación como una exención de esa regla. Este módulo solo registra procedencia y elegibilidad; no ejecuta esos usos.

Cuando el propietario ya ha confirmado las autorizaciones de usuarios y Fanvue, se puede registrar `authorized` y explicar en `basis` que se trata de su declaración (`satisfied_by_user_attestation`). El CLI no exige adjuntar documentos ni solicita esa confirmación de nuevo. `trainingReadiness=unsupported` describe el alcance de esta herramienta de metadatos, no una denegación de la autorización registrada. La falta de evidencia de ingresos o de revisión de calidad es un estado independiente.

## Procedencia y partición

Cada conversación registra un archivo y hash, una clave estable, el primer y último ID, cantidad de mensajes, intervalo temporal y truncamiento. **`conversationKey` debe ser estable dentro de la cuenta**: un ID local como `chat_001`, regenerado en cada exportación, no identifica por sí solo una conversación global. Mantener el vínculo privado con la fuente autorizada.

El módulo verifica el hash de los archivos sin interpretar su texto. La existencia del archivo y la coincidencia del hash no prueban que el rango declarado corresponda exactamente a su contenido; esa comprobación pertenece a la revisión de captación.

La partición predeterminada es por **cuenta**, usando un hash determinista del `accountId` y una semilla fijada. Todas sus conversaciones y conexiones van a `development` o `holdout`. El orden de entrada no cambia la asignación. También se rechaza reutilizar una misma conversación de un archivo entre particiones.

La alternativa `unit=conversation` incluye un aviso: permite que información de la misma cuenta aparezca en desarrollo y evaluación. Usar la partición por cuenta para la comparación principal. Con pocas cuentas puede quedar una partición vacía; ampliar la muestra y mantener la semilla, en vez de escoger una semilla después de observar resultados. Revisar aparte duplicados semánticos y fans compartidos entre cuentas; el hash de archivos no resuelve esas fugas.

El conjunto de `development` sirve para revisar hipótesis. Reservar `holdout` sin consultar sus resultados al ajustar el comportamiento. La selección de cuentas con ingresos introduce sesgo de supervivencia: añadir comparaciones de ofertas aceptadas, rechazadas y resultados desconocidos dentro de fuentes válidas. Un patrón asociado a ingresos no demuestra qué los causó.

## Entrada y ejecución

El esquema de entrada es `fanvue.research-cohort-input.v1`; los modelos Pydantic de `lab/research_cohort.py` son el contrato completo. No admite campos desconocidos ni texto de chats. Los archivos de evidencia se referencian con rutas relativas al directorio del manifiesto; no se permiten escapes con `..`, rutas absolutas ni enlaces simbólicos.

```bash
.venv/bin/python -m lab.research_cohort \
  --input lab/.data/private-real-chats/mi-cohorte/manifest.json \
  --output lab/.data/private-real-chats/mi-cohorte/cohort-review.json
```

El terminal solo muestra estado, recuentos y un código fijo de error. El archivo de salida conserva identidades y referencias privadas, por lo que no debe publicarse. Dentro del repositorio, las entradas y salidas del CLI se limitan a `lab/.data/private-real-chats/`, ya ignorado por Git. También se admiten rutas privadas fuera del repositorio. Las nuevas salidas usan `0600`, los directorios nuevos `0700`, y nunca se sobrescriben archivos.

### Convertir el inventario de candidatos

Este adaptador conserva los datos desconocidos. No convierte `revenueUsd`, actividad ni presencia de token en evidencia de ingresos. El resultado necesita autorizaciones y evidencias revisadas antes de admitir conversaciones.

```python
from pathlib import Path
from lab.research_cohort import read_manifest, write_private, compile_cohort

directory = Path("lab/.data/private-real-chats/mi-cohorte").resolve()
inventory = read_manifest(directory / "inventory_private.json")
assert inventory["schemaVersion"] == "fanvue.cohort-inventory.v1"

manifest = {
    "schemaVersion": "fanvue.research-cohort-input.v1",
    "purpose": "offline_conversation_research",
    "authorizations": {
        "analysis": "not_recorded",
        "evaluation": "not_recorded",
        "training": "not_recorded",
        "basis": "Completar con la autorización ya documentada para cada uso.",
    },
    "exclusions": [
        {
            **{k: item[k] for k in ("accountId", "connectionId", "handle") if item.get(k)},
            "reason": "owner_declared_test",
        }
        for item in inventory["exclusions"]
    ],
    "split": {"unit": "account", "seed": "cohort-v1-before-review", "holdoutPercent": 20},
    "accounts": [
        {
            "accountKey": item["alias"],
            "identity": {k: item[k] for k in ("accountId", "connectionId", "handle") if item.get(k)},
            "classification": item["sourceClass"],
            "classificationBasis": "Inventario de metadatos; verificar origen real por separado.",
            "observedAt": inventory["collectedAt"],
            "active": item["connectionActive"],
            "revenueEvidence": [],
            "conversations": [],
        }
        for item in inventory["candidates"]
    ],
}
write_private(directory / "manifest.json", manifest)
result = compile_cohort(manifest, evidence_directory=directory)
write_private(directory / "cohort-review.json", result)
```

Registrar las autorizaciones existentes con su alcance real; no volver a pedirlas por el mero uso del adaptador. Añadir evidencias de ingresos solo después de consultar la API o un export verificable y guardar el respaldo en privado. Cuando falte evidencia, la cuenta permanece pendiente.

## Verificación local

```bash
.venv/bin/python -m pytest tests/test_research_cohort.py -q
```

Las pruebas utilizan identidades ficticias y archivos sintéticos. Cubren precedencia de exclusiones y propagación entre conexiones, ingresos ausentes frente a cero o negativos, separación de acciones, atribución y duplicados de pagos, integridad de archivos, particiones estables, metadatos no admitidos y guardado privado. No consumen créditos, no abren conversaciones de clientes y no llaman a Fanvue.
