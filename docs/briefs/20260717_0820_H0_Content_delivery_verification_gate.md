# Redesign brief (auto-generated from live chats)

Paste this into a Cursor chat with the redesign agent. Review, then say merge/deploy if OK.

### 1. Problema medible
Emma claimed photo sent 3+ times when nothing was delivered, then doubled down. No system check prevents false claims.

### 2. Por qué auto-fix no basta
Requires integration with content delivery system to verify send status before allowing claim language in response generation.

### 3. Diseño propuesto
- Soft or Hard: **Hard**
- Design: Add pre-generation check: if reply contains claim of sent content, verify against delivery log. If unconfirmed, block claim and inject apology template instead.
- Files to touch: response_generator.py, content_delivery.py

### 4. Qué NO cambia
OAuth, tokens, .env, vault prices, secrets. No drive-by refactors.

### 5. Criterio de éxito + verificación
- Success: the repeated critic pattern for this issue stops appearing on the improve board.
- Verify: `python -c "import scripts.poll_inbox"` + watch Railway logs / next improve_once digest.

### 6. Rollback
`git revert` the merge commit / redeploy previous Railway image.

---
You are the Emma Fanvue redesign agent. Follow docs/REDESIGN_BRIEF.md.
Soft first if possible. Branch only. NEVER push main / railway up unless human asks.
