# Comparación privada de la capa de prompt

`lab.behavior_eval` compara la persona de laboratorio con la misma persona más
`behavior_rules_v2.md`, usando exactamente los mismos mensajes visibles en cada par.
El alcance registrado es `isolated_persona_prompt_layer`: **no ejecuta
`lab.policy.build_context`, memoria comercial, el poller ni el recorrido completo
del bot**. Es una regresión de desarrollo sobre casos adaptados, no un holdout
independiente ni una medida de conversión, entrenamiento o rendimiento en producción.

El JSONL de casos contiene `id` e `inputMessages`. El sidecar
`fanvue.behavior-evaluation-review.v1` liga los bytes exactos del JSONL, sus IDs
ordenados, aprobación de inputs no explícitos, revisor, propósito
`offline_response_evaluation` y clasificación `development_regression`. Referencias,
rúbricas y metadatos de origen se excluyen de las peticiones. Ambos archivos se leen
una sola vez para que los hashes registrados describan los bytes validados.

El plan admite hasta nueve casos, dos variantes y 18 peticiones. Fija DeepSeek
`deepseek/deepseek-v4.1-flash-1017`, `deepinfra/fp8`, ZDR, `data_collection=deny`,
sin fallbacks, caché desactivada, razonamiento bajo y 1.024 tokens de salida.
Los topes de enrutamiento son 1 USD/millón de entrada, 5 USD/millón de salida y
cero por solicitud. La estimación total y el presupuesto no pueden superar
0,50 USD. La estimación conservadora no es una factura ni garantiza el cobro final.

Sin `--live` sólo se validan entradas y se imprime el resumen estimado. En modo
live se valida primero un destino nuevo y privado, antes de cargar configuración
o construir un cliente. Cada petición guarda un marcador `request_NNN.json`
antes de enviarse y un `response_NNN.json` después; el marcador identifica el hash
del payload y no contiene la clave. No hay reintentos ni reanudación implícita de
un directorio existente. Un marcador sin respuesta deja resultado y coste
desconocidos: no volver a ejecutar en otra carpeta para rescatarlo sin reconciliar
esa llamada. Los controles de duplicación no son un registro global entre carpetas.

El proceso se detiene tras cualquier error, coste desconocido o presupuesto que no
permita la siguiente llamada. Un coste informado que exceda el presupuesto también
invalida la finalización, aunque llegue en la última respuesta. Los textos quedan
`unreviewed_response`; no se asignan puntuaciones de calidad automáticamente.
Archivos nuevos `0600`, directorios nuevos `0700`; ningún artefacto real pertenece a Git.

```bash
python -m lab.behavior_eval --cases /private/cases.jsonl --review /private/review.json
python -m lab.behavior_eval --cases /private/cases.jsonl --review /private/review.json \
  --output-dir /private/new-run --budget-usd 0.50 --env-file /private/existing.env.lab --live
python -m unittest discover -s tests -p test_behavior_eval.py -v
```

Las pruebas usan exclusivamente datos sintéticos y HTTP simulado. Esta utilidad no
crea un modelo entrenado y sus resultados no autorizan por sí solos cambios en el bot.
