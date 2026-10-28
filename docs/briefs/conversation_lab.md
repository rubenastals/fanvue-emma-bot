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
