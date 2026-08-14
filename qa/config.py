"""Client-side settings for the desktop tool.

Deliberately a separate file from the service's config.json: two processes
writing one JSON file is a race waiting to happen, and these knobs are about
your desktop, not your model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    # Put the previous clipboard contents back after pasting.
    "restore_clipboard": True,
    # "auto" sniffs the focused window (X11 only) and uses Ctrl+Shift+V for
    # terminals. Force with "ctrl+v" or "ctrl+shift+v".
    "paste_key": "auto",
    # Type the result instead of pasting it. Slower, but survives apps with
    # unusual paste handling and never touches the clipboard.
    "use_typing": False,
    # Show the streaming preview window for every run, not just --preview.
    "always_preview": False,
    # Refuse to send more than this many characters in one go.
    "max_chars": 20000,
    # Say something on success. Off by default: you can see the text change.
    "notify_success": False,
    # "auto" | "rofi" | "wofi" | "fuzzel" | "dmenu" | "zenity" | "tk"
    "picker": "auto",
    # Actions offered in the picker. Empty list means all of them.
    "picker_actions": [],
}


def path() -> Path:
    override = os.getenv("QUICKAI_CLIENT_CONFIG")
    if override:
        return Path(override).expanduser()
    base = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "quickai" / "client.json"


def load() -> Dict[str, Any]:
    config = dict(DEFAULTS)
    file = path()
    if file.exists():
        try:
            stored = json.loads(file.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                config.update(stored)
        except (ValueError, OSError):
            pass
    else:
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")
        except OSError:
            pass
    return config


def cache_dir() -> Path:
    base = os.getenv("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    directory = Path(base).expanduser() / "quickai"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
