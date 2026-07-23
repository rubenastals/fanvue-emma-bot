#!/usr/bin/env bash
# Load project .env before agent shell commands (local Cursor).
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ENV_FILE="$ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
