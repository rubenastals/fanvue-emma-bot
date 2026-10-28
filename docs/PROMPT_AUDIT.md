# Prompt / behavior audit

Soft / DeepSeek / autofix changes are logged here.
**Live chat prompt = CORE + CLIENT CARD + history + turn context only.**
Soft lessons do **not** enter the live prompt unless `INJECT_LESSONS=1`.

| when (UTC) | source | action | in live? | detail |
|---|---|---|---|---|
| `2026-10-28T10:44:21` | operator_style_preference | retain_selected_lab_baseline | no | 24-response trial did not establish improvement: repeated questions and an unauthorized alternative offer persisted. Ret [lab/fixtures/persona.md] |
| `2026-10-28T10:38:35` | operator_style_preference | calibrate_lab_persona | no | Selected playful alternative B (DeepSeek) in one response pair. Replace the lab style paragraph; retain prior prompt in  [lab/fixtures/persona.md] |
| `2026-07-18T22:27:09` | critic | propose_soft_lesson | no | Never invent a lock or candado when lock=NONE. When a fan gives short, non-committal replies, de-escalate and reconnect  |
| `2026-07-18T22:27:00` | critic | propose_soft_lesson | no | Ruben responds to sweet, direct affection but shuts down when pressured with jealousy or repeated FOMO. He needs soft, g |
| `2026-07-17T09:40:43` | test | architecture_check | no | layered prompt live |
