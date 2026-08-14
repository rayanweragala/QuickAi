#!/usr/bin/env bash
# Run QuickAI in the foreground (development / first try).
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtualenv…"
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -r requirements.txt
fi

# Load .env if present (QUICKAI_HOST, QUICKAI_PORT, QUICKAI_BASE_URL, …)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export QUICKAI_HOST="${QUICKAI_HOST:-127.0.0.1}"
export QUICKAI_PORT="${QUICKAI_PORT:-7431}"

echo "QuickAI → http://${QUICKAI_HOST}:${QUICKAI_PORT}"
exec ./.venv/bin/python -m app.main
