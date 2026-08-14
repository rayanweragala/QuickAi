#!/usr/bin/env bash
#
# Install QuickAI as a systemd *user* service (no sudo, no root).
#
#   ./install.sh                       # localhost:7431
#   ./install.sh --port 7431 --url http://127.0.0.1:8000
#   ./install.sh --host 0.0.0.0 --token mysecret   # let the LAN in
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/quickai"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="quickai.service"

HOST="127.0.0.1"
PORT="7431"
BASE_URL=""
TOKEN=""

while [ $# -gt 0 ]; do
  case "$1" in
    --host)  HOST="$2"; shift 2 ;;
    --port)  PORT="$2"; shift 2 ;;
    --url)   BASE_URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
if ! python3 -c 'import venv' 2>/dev/null; then
  echo "python3-venv is missing. Install it first:  sudo apt install python3-venv"
  exit 1
fi
command -v systemctl >/dev/null || { echo "systemd is required for install.sh (use ./run.sh instead)"; exit 1; }

say "Creating virtualenv in $APP_DIR/.venv"
[ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" >/dev/null
say "Dependencies installed"

mkdir -p "$CONFIG_DIR" "$UNIT_DIR"

# Seed .env only on a fresh install so re-running never clobbers your edits.
if [ ! -f "$APP_DIR/.env" ]; then
  {
    echo "QUICKAI_HOST=$HOST"
    echo "QUICKAI_PORT=$PORT"
    [ -n "$BASE_URL" ] && echo "QUICKAI_BASE_URL=$BASE_URL"
    [ -n "$TOKEN" ] && echo "QUICKAI_TOKEN=$TOKEN"
  } > "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  say "Wrote $APP_DIR/.env"
else
  say "Keeping your existing .env"
fi

sed \
  -e "s|__APP_DIR__|$APP_DIR|g" \
  -e "s|__CONFIG_DIR__|$CONFIG_DIR|g" \
  -e "s|__HOST__|$HOST|g" \
  -e "s|__PORT__|$PORT|g" \
  "$APP_DIR/scripts/quickai.service.template" > "$UNIT_DIR/$UNIT"
say "Installed unit $UNIT_DIR/$UNIT"

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"

# Without lingering, user services stop when you log out and only start at
# login rather than at boot.
if ! loginctl show-user "$USER" 2>/dev/null | grep -q 'Linger=yes'; then
  warn "Enabling linger so QuickAI starts at boot (may ask for your password):"
  sudo loginctl enable-linger "$USER" || warn "Skipped — QuickAI will start when you log in."
fi

sleep 1
if systemctl --user is-active --quiet "$UNIT"; then
  say "QuickAI is running"
else
  warn "Service did not start. Logs:"
  journalctl --user -u "$UNIT" -n 30 --no-pager || true
  exit 1
fi

URL="http://$HOST:$PORT"
[ "$HOST" = "0.0.0.0" ] && URL="http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT"
[ -n "$TOKEN" ] && URL="$URL/?token=$TOKEN"

echo
say "Open  $URL"
echo "    logs      journalctl --user -u $UNIT -f"
echo "    restart   systemctl --user restart $UNIT"
echo "    remove    ./uninstall.sh"
echo
echo "Set your endpoint URL and model from Settings in the top right."
