#!/usr/bin/env bash
# Remove the systemd user service. Your settings in ~/.config/quickai are kept
# unless you pass --purge.
set -euo pipefail

UNIT="quickai.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/quickai"

systemctl --user disable --now "$UNIT" 2>/dev/null || true
rm -f "$UNIT_DIR/$UNIT"
systemctl --user daemon-reload
echo "Service removed."

if [ "${1:-}" = "--purge" ]; then
  rm -rf "$CONFIG_DIR"
  echo "Deleted $CONFIG_DIR"
else
  echo "Settings kept in $CONFIG_DIR (use --purge to delete them)."
fi
