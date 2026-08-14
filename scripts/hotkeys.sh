#!/usr/bin/env bash
#
# Register (or remove) the QuickAI global hotkeys.
#
#   scripts/hotkeys.sh install
#   scripts/hotkeys.sh list
#   scripts/hotkeys.sh remove
#
# GNOME: written straight into gsettings, no clicking through Settings.
# KDE:   .desktop files with X-KDE-Shortcuts.
# Other: prints the config lines to paste into your WM.
#
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
QA="$REPO/bin/qa"
[ -x "$HOME/.local/bin/qa" ] && QA="$HOME/.local/bin/qa"

SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
BASE="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

# key | name | binding | command args
BINDINGS=(
  "quickai-menu|QuickAI menu|<Control><Alt>space|menu"
  "quickai-grammar|QuickAI fix grammar|<Control><Alt>g|run grammar"
  "quickai-polish|QuickAI polish|<Control><Alt>p|run polish"
  "quickai-reply|QuickAI reply to email|<Control><Alt>r|run reply --preview"
  "quickai-prompt|QuickAI make agent prompt|<Control><Alt>m|run prompt"
  "quickai-ask|QuickAI ask|<Control><Alt>a|ask"
  "quickai-undo|QuickAI undo|<Control><Alt>z|undo"
)

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

desktop_kind() {
  local d="${XDG_CURRENT_DESKTOP:-}${DESKTOP_SESSION:-}"
  case "${d,,}" in
    *gnome*|*unity*|*cinnamon*|*pop*) echo gnome ;;
    *kde*|*plasma*)                   echo kde ;;
    *sway*|*hypr*|*i3*|*wlroots*)     echo tiling ;;
    *)                                echo other ;;
  esac
}

# ─────────────────────────────── GNOME ───────────────────────────────

gnome_paths() {
  python3 - "$@" <<'PY'
import subprocess, sys, ast
schema = "org.gnome.settings-daemon.plugins.media-keys"
raw = subprocess.run(["gsettings", "get", schema, "custom-keybindings"],
                     capture_output=True, text=True).stdout.strip()
try:
    current = ast.literal_eval(raw) if raw and raw != "@as []" else []
except (ValueError, SyntaxError):
    current = []
print("\n".join(current))
PY
}

gnome_set_list() {
  python3 - "$@" <<'PY'
import subprocess, sys
schema = "org.gnome.settings-daemon.plugins.media-keys"
paths = [p for p in sys.argv[1:] if p]
value = "[" + ", ".join(f"'{p}'" for p in paths) + "]"
subprocess.run(["gsettings", "set", schema, "custom-keybindings", value], check=True)
PY
}

gnome_install() {
  command -v gsettings >/dev/null || { warn "gsettings not found"; return 1; }

  mapfile -t existing < <(gnome_paths)
  local wanted=()
  for entry in "${BINDINGS[@]}"; do
    IFS='|' read -r key name binding cmd <<< "$entry"
    local path="$BASE/$key/"
    wanted+=("$path")

    gsettings set "$SCHEMA.custom-keybinding:$path" name    "$name"
    gsettings set "$SCHEMA.custom-keybinding:$path" command "$QA $cmd"
    gsettings set "$SCHEMA.custom-keybinding:$path" binding "$binding"
    printf '    %-22s %s\n' "$binding" "$name"
  done

  # Keep anything the user already had, drop duplicates of ours.
  local merged=()
  for path in "${existing[@]}"; do
    [[ "$path" == *"/quickai-"* ]] && continue
    [ -n "$path" ] && merged+=("$path")
  done
  merged+=("${wanted[@]}")
  gnome_set_list "${merged[@]}"
  say "Registered ${#wanted[@]} GNOME shortcuts"
}

gnome_remove() {
  command -v gsettings >/dev/null || return 0
  mapfile -t existing < <(gnome_paths)
  local kept=()
  for path in "${existing[@]}"; do
    [[ "$path" == *"/quickai-"* ]] && continue
    [ -n "$path" ] && kept+=("$path")
  done
  gnome_set_list "${kept[@]}"
  for entry in "${BINDINGS[@]}"; do
    IFS='|' read -r key _ _ _ <<< "$entry"
    dconf reset -f "$BASE/$key/" 2>/dev/null || true
  done
  say "GNOME shortcuts removed"
}

gnome_list() {
  mapfile -t existing < <(gnome_paths)
  for path in "${existing[@]}"; do
    [[ "$path" != *"/quickai-"* ]] && continue
    printf '    %-22s %s\n' \
      "$(gsettings get "$SCHEMA.custom-keybinding:$path" binding | tr -d "'")" \
      "$(gsettings get "$SCHEMA.custom-keybinding:$path" command | tr -d "'")"
  done
}

# ──────────────────────────────── KDE ────────────────────────────────

kde_install() {
  local dir="$HOME/.local/share/applications"
  mkdir -p "$dir"
  for entry in "${BINDINGS[@]}"; do
    IFS='|' read -r key name binding cmd <<< "$entry"
    # KDE wants Ctrl+Alt+G rather than GNOME's <Control><Alt>g
    local kde_binding
    kde_binding="$(echo "$binding" | sed -e 's/<Control>/Ctrl+/g' -e 's/<Alt>/Alt+/g' \
                                          -e 's/<Shift>/Shift+/g' -e 's/<Super>/Meta+/g')"
    kde_binding="${kde_binding^}"
    cat > "$dir/$key.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Exec=$QA $cmd
NoDisplay=true
X-KDE-Shortcuts=$kde_binding
EOF
    printf '    %-22s %s\n' "$kde_binding" "$name"
  done
  command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || \
  command -v kbuildsycoca5 >/dev/null && kbuildsycoca5 >/dev/null 2>&1 || true
  say "Wrote KDE shortcut files to $dir"
  warn "If a shortcut does not fire, open System Settings → Shortcuts and confirm it."
}

kde_remove() {
  for entry in "${BINDINGS[@]}"; do
    IFS='|' read -r key _ _ _ <<< "$entry"
    rm -f "$HOME/.local/share/applications/$key.desktop"
  done
  say "KDE shortcut files removed"
}

# ─────────────────────────────── other ───────────────────────────────

print_manual() {
  echo
  say "Add these to your window manager config:"
  echo
  echo "  # sway / i3"
  for entry in "${BINDINGS[@]}"; do
    IFS='|' read -r _ name binding cmd <<< "$entry"
    local sway
    sway="$(echo "$binding" | sed -e 's/<Control>/Ctrl+/g' -e 's/<Alt>/Mod1+/g' \
                                  -e 's/<Super>/Mod4+/g' -e 's/<Shift>/Shift+/g')"
    printf '  bindsym %-20s exec %s %s\n' "${sway%+}" "$QA" "$cmd"
  done
  echo
  echo "  # hyprland"
  for entry in "${BINDINGS[@]}"; do
    IFS='|' read -r _ name binding cmd <<< "$entry"
    local key="${binding##*>}"
    printf '  bind = CTRL ALT, %s, exec, %s %s\n' "${key^^}" "$QA" "$cmd"
  done
  echo
}

# ─────────────────────────────── main ────────────────────────────────

ACTION="${1:-install}"
KIND="$(desktop_kind)"

case "$ACTION" in
  install)
    say "Desktop looks like: $KIND"
    case "$KIND" in
      gnome) gnome_install || print_manual ;;
      kde)   kde_install   || print_manual ;;
      *)     print_manual ;;
    esac
    echo
    say "Try it: select some text in any app and press Ctrl+Alt+Space"
    ;;
  remove)
    case "$KIND" in
      gnome) gnome_remove ;;
      kde)   kde_remove ;;
      *)     warn "Nothing to remove — these were manual bindings." ;;
    esac
    ;;
  list)
    case "$KIND" in
      gnome) gnome_list ;;
      kde)   ls -1 "$HOME/.local/share/applications"/quickai-*.desktop 2>/dev/null || echo "    none" ;;
      *)     print_manual ;;
    esac
    ;;
  *)
    echo "usage: $0 [install|list|remove]" >&2
    exit 1
    ;;
esac
