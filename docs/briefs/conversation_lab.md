# Conversation lab — implementation brief

## 1. Problema medible

The inspected main commit is a889aa7eed7c931cac4509ff133b1a3c19f507d4. The default persona contains about 10,300 characters while core/prompt_layers.py limits CORE to 5,600. The live response path sanitizes before returning a draft and again afterwards; the simulator cannot currently compare an original model response with each subsequent stage. There is no interactive, isolated comparison UI. This is static evidence, not a claim about production configuration or measured conversion.

## 2. Por qué el auto-fix no basta

A prompt edit alone cannot make context, model outputs and transformations observable, or support repeatable human evaluation. The single thesis of this change is an isolated conversation and evaluation laboratory.

## 3. Diseño propuesto

Add lab/ with an independent FastAPI entry point, SQLite storage, synthetic fixtures, a Spanish UI, explicit fixture and real-provider modes, versioned conversation snapshots, candidate review, model comparison, export and human ratings. Add optional tracing at the existing live response seam while preserving its default behavior. Reuse the repository's prompt layering where appropriate. Providers receive the same snapshot. Evaluation fixtures are non-graphic and contain no real fan data. Provider errors remain errors.

## 4. Qué NO cambia

The live persona, OAuth, poller behavior, Fanvue sending, production database schema, vault content/prices and secrets are unchanged. The laboratory never calls Fanvue. It has a separate persistence directory and creates no automatic revenue or quality claims.

## 5. Criterio de éxito + verificación

Exercise the browser-to-API workflow with synthetic fixtures; test corrections, persistent opt-out, duplicate payments, acquired media, account isolation, stale approvals, human pause, candidate snapshot equality, provider errors and secret redaction. Validate the real provider HTTP contract using a local mock service. Execute the repository-required import smoke check. Live model quality remains unmeasured until provider credentials are available and actual conversations are reviewed.

## 6. Clase de cambio

Hard, on feat/conversation-lab. New storage is additive and isolated. Review through a draft pull request. No merge to main or Railway deployment is part of this change.

## 7. Plan de rollback

Stop the separate lab process and revert this branch's commit. Optional tracing defaults off. Production persistence and send behavior require no rollback or migration.

## 8. Calibración de estilo — 28 de octubre de 2026

El operador eligió la alternativa B de un duelo de tono juguetón, correspondiente a DeepSeek V4.1 Flash. Es una preferencia humana sobre una respuesta concreta, no una puntuación general del modelo. Hipótesis: un personaje de laboratorio con humor breve, reacciones específicas y menos preguntas mecánicas se acercará a esa preferencia.

Se probó sustituir únicamente el párrafo de estilo de `lab/fixtures/persona.md`; el ejemplo elegido no se incorporó al prompt. Se compararon DeepSeek y Grok con el mismo personaje revisado en seis casos existentes (recuerdo, precio, objeción, baja comercial, acceso a una compra e identidad) y el mismo diálogo de seis turnos. Se completaron las 24 respuestas reales previstas, guardando las versiones del prompt, las salidas y los costes. En el diálogo, cada modelo conserva sus propias respuestas anteriores. La revisión automática es cualitativa y separada de la preferencia humana. Sin repeticiones ni un control simultáneo con el prompt anterior, esta ronda no demuestra una mejora causada por el ajuste ni superioridad estadística.

La variante (`lab-persona-aed0eae53c9f`) no demostró una mejora suficiente para conservarla: DeepSeek encadenó preguntas en sus cuatro primeros turnos y ofreció un pack alternativo en el caso de objeción, pese a `CONTINUE_CHAT`. Se restauró la persona que produjo la B elegida. El lote de terminal usa por defecto DeepSeek como candidato de estilo y Grok como comparación; los demás modelos siguen disponibles. Los casos, proveedores y persona de producción permanecen iguales. Los problemas de descripciones ficticias y rutas de acceso no verificadas se mantienen visibles para evaluarlos por separado.

La ejecución descubrió además un falso positivo reproducible del validador: «Hoy no quieres comprar nada» se interpretaba como propuesta comercial. Se corrige después de la ronda con una regresión negativa y propuestas reales como controles positivos, sin modificar las inferencias, las decisiones ni las advertencias históricas guardadas.
