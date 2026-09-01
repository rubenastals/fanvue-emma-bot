#!/usr/bin/env bash
# Audit Railway consumption for fanvue-emma-bot.
# Requires: railway CLI + `railway login` (or RAILWAY_API_TOKEN).
set -euo pipefail

export PATH="${HOME}/.railway/bin:${PATH}"
PERIOD="${1:-previous}"
SINCE="${2:-7d}"

echo "=== Railway auth ==="
if ! railway whoami --json >/tmp/railway_whoami.json 2>/dev/null; then
  echo "Not logged in. Run: railway login"
  exit 1
fi
python3 - <<'PY'
import json
d = json.load(open("/tmp/railway_whoami.json"))
user = d.get("user") or {}
print(f"user: {user.get('email') or user.get('name') or d}")
ws = d.get("workspaces") or []
for w in ws[:5]:
    print(f"  workspace: {w.get('name')} id={w.get('id')}")
PY

echo
echo "=== Workspace usage (period=${PERIOD}) ==="
railway usage --period "${PERIOD}" --json | python3 -m json.tool

echo
echo "=== Usage by project (period=${PERIOD}) ==="
railway usage projects --period "${PERIOD}" --json | python3 -m json.tool

echo
echo "=== Linked project status ==="
railway status --json 2>/dev/null | python3 -m json.tool || echo "(not linked — cd to repo and run railway link)"

echo
echo "=== Services in linked environment ==="
railway service list --json 2>/dev/null | python3 -m json.tool || true

echo
echo "=== Resource metrics last ${SINCE} (all services) ==="
railway metrics --all --since "${SINCE}" --json 2>/dev/null | python3 -m json.tool || true

echo
echo "=== CPU + memory detail per service ==="
for svc in $(railway service list --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(' '.join((x.get('name') or '') for x in (d if isinstance(d,list) else d.get('services',d))))" 2>/dev/null); do
  [ -z "$svc" ] && continue
  echo "--- service: $svc ---"
  railway metrics --service "$svc" --since "${SINCE}" --cpu --memory --network --volume --json 2>/dev/null | python3 -m json.tool || true
done

echo
echo "=== Recent deployments (crash loops?) ==="
railway deployment list --limit 15 --json 2>/dev/null | python3 -m json.tool || true

echo
echo "=== Usage limits ==="
railway usage limit status --json 2>/dev/null | python3 -m json.tool || true

echo
echo "=== Cost suspects in this repo ==="
echo "  • Each 24/7 poller service = full CPU/RAM billing"
echo "  • Postgres + Redis plugins = always-on compute + disk"
echo "  • Dockerfile installs Node.js + @cursor/sdk (heavier RAM)"
echo "  • HOUR_REVIEW_ENABLED=1 (default) spawns Node every hour on poller"
echo "  • Second model (Sophia) = duplicate poller service if deployed"
echo
echo "Dashboard: railway open  (Usage tab shows line-item breakdown)"
