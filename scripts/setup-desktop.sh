#!/usr/bin/env bash
#
# Set up select-text-press-hotkey on this machine.
#
#   scripts/setup-desktop.sh            # detect, install, register hotkeys
#   scripts/setup-desktop.sh --no-sudo  # skip anything needing root
#   scripts/setup-desktop.sh --no-keys  # skip hotkey registration
#
# Safe to re-run.
#
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
USE_SUDO=1
DO_KEYS=1

while [ $# -gt 0 ]; do
  case "$1" in
    --no-sudo) USE_SUDO=0; shift ;;
    --no-keys) DO_KEYS=0; shift ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ok\033[0m %s\n' "$*"; }

SESSION="${XDG_SESSION_TYPE:-}"
if [ -z "$SESSION" ]; then
  [ -n "${WAYLAND_DISPLAY:-}" ] && SESSION=wayland || SESSION=x11
fi
say "Session type: $SESSION   Desktop: ${XDG_CURRENT_DESKTOP:-unknown}"

apt_install() {
  local pkgs=("$@") missing=()
  for pkg in "${pkgs[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  [ ${#missing[@]} -eq 0 ] && { ok "already installed: ${pkgs[*]}"; return 0; }
  if [ "$USE_SUDO" -eq 0 ]; then
    warn "would install: ${missing[*]} (skipped, --no-sudo)"
    return 1
  fi
  say "Installing: ${missing[*]}"
  sudo apt-get update -qq
  sudo apt-get install -y "${missing[@]}"
}

# ── 1. clipboard + input tools ────────────────────────────────────────────────

COMMON=(libnotify-bin python3-tk)

if [ "$SESSION" = "wayland" ]; then
  apt_install wl-clipboard "${COMMON[@]}" || true
  # A picker that matches Wayland desktops; harmless if it fails.
  apt_install wofi 2>/dev/null || warn "wofi not installed — the built-in Tk picker will be used"
else
  apt_install xclip xdotool "${COMMON[@]}" || true
  apt_install rofi 2>/dev/null || warn "rofi not installed — the built-in Tk picker will be used"
fi

# ── 2. Wayland: the part that needs root, once ────────────────────────────────

setup_ydotool() {
  say "Wayland blocks apps from typing into each other, so pasting the result"
  say "back needs ydotool, which talks to the kernel's /dev/uinput."

  apt_install ydotool || {
    warn "ydotool is not in your apt sources."
    warn "Build it from https://github.com/ReimuNotMoe/ydotool, then re-run this script."
    return 1
  }

  local rule=/etc/udev/rules.d/60-quickai-uinput.rules
  if [ ! -f "$rule" ]; then
    say "Adding a udev rule so your user can reach /dev/uinput"
    echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' \
      | sudo tee "$rule" >/dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=uinput || true
  else
    ok "udev rule already present"
  fi

  if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    say "Adding $USER to the 'input' group"
    sudo usermod -aG input "$USER"
    NEED_RELOGIN=1
  else
    ok "already in the 'input' group"
  fi

  # ydotoold as a user service, so it comes back after reboot.
  local unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/ydotoold.service"
  mkdir -p "$(dirname "$unit")"
  cat > "$unit" <<EOF
[Unit]
Description=ydotool daemon (input backend for QuickAI)

[Service]
Type=simple
ExecStart=$(command -v ydotoold) --socket-path=%t/.ydotool_socket --socket-own=$(id -u):$(id -g)
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now ydotoold.service 2>/dev/null || true
  sleep 1
  if systemctl --user is-active --quiet ydotoold.service; then
    ok "ydotoold is running"
  else
    warn "ydotoold did not start — usually because the group change is not active yet."
    NEED_RELOGIN=1
  fi
}

NEED_RELOGIN=0
if [ "$SESSION" = "wayland" ]; then
  case "${XDG_CURRENT_DESKTOP,,}" in
    *sway*|*hypr*|*wlroots*)
      say "wlroots compositor detected — trying wtype first (no root needed)"
      apt_install wtype || setup_ydotool || true
      ;;
    *)
      if [ "$USE_SUDO" -eq 1 ]; then
        setup_ydotool || true
      else
        warn "Skipping ydotool setup (--no-sudo). qa will copy to the clipboard instead."
      fi
      ;;
  esac
fi

# ── 3. put `qa` on your PATH ──────────────────────────────────────────────────

mkdir -p "$BIN_DIR"
chmod +x "$REPO/bin/qa"
ln -sf "$REPO/bin/qa" "$BIN_DIR/qa"
ok "linked $BIN_DIR/qa"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not on your PATH. Add this to ~/.bashrc:"
     echo '      export PATH="$HOME/.local/bin:$PATH"' ;;
esac

# ── 4. hotkeys ────────────────────────────────────────────────────────────────

if [ "$DO_KEYS" -eq 1 ]; then
  echo
  "$REPO/scripts/hotkeys.sh" install
fi

# ── 5. verdict ────────────────────────────────────────────────────────────────

echo
say "Checking what works now:"
echo
"$BIN_DIR/qa" doctor || true

if [ "$NEED_RELOGIN" -eq 1 ]; then
  echo
  warn "Log out and back in (or reboot) to activate the 'input' group."
  warn "Until then qa falls back to copying the result to your clipboard."
fi
