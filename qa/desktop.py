"""Everything that touches your desktop session.

The hard problem this file solves: reading the text you have selected in
another application, and putting the answer back where it came from — on both
X11 and Wayland, without you having to care which one you are running.

    X11      xclip/xsel read the PRIMARY selection (which is populated just by
             selecting text — no keystroke needed), xdotool synthesises the
             paste. Works everywhere including terminals. No permissions.

    Wayland  wl-paste --primary reads the selection the same way and needs no
             permissions either. Synthesising the paste is the restricted part:
             compositors deliberately refuse to let one app type into another.
             ydotool goes underneath the compositor via /dev/uinput (one-time
             sudo setup); wtype uses the virtual-keyboard protocol, which
             wlroots compositors like sway support but GNOME does not.

    Neither  We still read the selection through whatever tool exists, put the
             result on the clipboard, and tell you to press Ctrl+V. Degraded,
             but never broken.

Stdlib only, so `qa` runs under /usr/bin/python3 without the venv.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import List, Optional

# Linux input event codes, for ydotool. See linux/input-event-codes.h
KEY = {
    "leftctrl": 29, "rightctrl": 97,
    "leftshift": 42, "rightshift": 54,
    "leftalt": 56, "rightalt": 100,
    "leftmeta": 125, "rightmeta": 126,
    "v": 47, "c": 46, "insert": 110,
}

MODIFIER_CODES = [
    KEY["leftctrl"], KEY["rightctrl"],
    KEY["leftshift"], KEY["rightshift"],
    KEY["leftalt"], KEY["rightalt"],
    KEY["leftmeta"], KEY["rightmeta"],
]

# Window classes that need Ctrl+Shift+V instead of Ctrl+V.
TERMINAL_CLASSES = {
    "gnome-terminal", "gnome-terminal-server", "org.gnome.terminal",
    "ptyxis", "org.gnome.ptyxis", "konsole", "org.kde.konsole", "yakuake",
    "xterm", "uxterm", "urxvt", "rxvt", "st-256color", "alacritty",
    "org.wezfurlong.wezterm", "wezterm", "kitty", "terminator", "tilix",
    "guake", "hyper", "foot", "footclient", "xfce4-terminal", "mate-terminal",
    "lxterminal", "qterminal", "deepin-terminal", "warp", "contour",
}


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _run(cmd: List[str], stdin: Optional[str] = None, timeout: float = 5.0,
         capture: bool = True):
    """Run a command, never raise. Returns CompletedProcess or None.

    `capture=False` matters more than it looks. Clipboard writers (xclip, xsel,
    wl-copy) fork a background process that keeps ownership of the selection
    after the parent exits — and that child inherits our stdout pipe. If we
    captured it, subprocess.run would sit waiting for a pipe that nobody is
    ever going to close, hit the timeout, and report failure for a write that
    actually succeeded.
    """
    sink = subprocess.PIPE if capture else subprocess.DEVNULL
    try:
        return subprocess.run(
            cmd,
            input=stdin.encode("utf-8") if stdin is not None else None,
            stdout=sink,
            stderr=sink,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------- detection --

@dataclass
class Session:
    kind: str = "unknown"          # "x11" | "wayland" | "unknown"
    desktop: str = ""              # GNOME, KDE, sway, …
    reader: str = ""               # tool used to read the selection
    writer: str = ""               # tool used to set the clipboard
    typer: str = ""                # "xdotool" | "ydotool" | "wtype" | ""
    notes: List[str] = field(default_factory=list)

    @property
    def can_replace(self) -> bool:
        """True when we can put text back without you pressing anything."""
        return bool(self.typer)

    @property
    def can_read(self) -> bool:
        return bool(self.reader)


def detect() -> Session:
    session = Session()
    session.desktop = os.getenv("XDG_CURRENT_DESKTOP", "") or os.getenv("DESKTOP_SESSION", "")

    kind = (os.getenv("XDG_SESSION_TYPE") or "").lower()
    if kind not in ("x11", "wayland"):
        # Env var missing (common when launched from a bare systemd unit):
        # infer from which display sockets are present.
        if os.getenv("WAYLAND_DISPLAY"):
            kind = "wayland"
        elif os.getenv("DISPLAY"):
            kind = "x11"
        else:
            kind = "unknown"
    session.kind = kind

    if kind == "wayland":
        if have("wl-paste"):
            session.reader = "wl-paste"
            session.writer = "wl-copy"
        elif have("xclip") and os.getenv("DISPLAY"):
            # XWayland fallback: only sees X11 clients, but better than nothing.
            session.reader = "xclip"
            session.writer = "xclip"
            session.notes.append("Using xclip through XWayland; native Wayland apps will not share their selection.")
        else:
            session.notes.append("Install wl-clipboard to read the selection: sudo apt install wl-clipboard")

        if have("ydotool") and _ydotool_ready():
            session.typer = "ydotool"
        elif have("wtype"):
            session.typer = "wtype"
            session.notes.append("Using wtype — works on wlroots compositors (sway, Hyprland) but not GNOME or KDE.")
        elif have("ydotool"):
            session.notes.append("ydotool is installed but its daemon is not reachable. Run: scripts/setup-desktop.sh")
        else:
            session.notes.append("No way to paste automatically on Wayland. Run: scripts/setup-desktop.sh")

    elif kind == "x11":
        if have("xclip"):
            session.reader = session.writer = "xclip"
        elif have("xsel"):
            session.reader = session.writer = "xsel"
        else:
            session.notes.append("Install xclip to read the selection: sudo apt install xclip")

        if have("xdotool"):
            session.typer = "xdotool"
        else:
            session.notes.append("Install xdotool to paste automatically: sudo apt install xdotool")
    else:
        session.notes.append("No graphical session detected (no DISPLAY or WAYLAND_DISPLAY).")

    return session


def _ydotool_ready() -> bool:
    """ydotool without a running ydotoold just hangs or errors."""
    sock = os.getenv("YDOTOOL_SOCKET") or f"/run/user/{os.getuid()}/.ydotool_socket"
    if os.path.exists(sock):
        return True
    for candidate in ("/tmp/.ydotool_socket", os.path.expanduser("~/.ydotool_socket")):
        if os.path.exists(candidate):
            os.environ.setdefault("YDOTOOL_SOCKET", candidate)
            return True
    # Some builds talk to /dev/uinput directly without a daemon.
    return os.access("/dev/uinput", os.W_OK)


# ---------------------------------------------------------------- reading ---

def get_selection(session: Session) -> str:
    """The text you have highlighted, via the PRIMARY selection.

    PRIMARY is filled in the moment you drag over text — no Ctrl+C needed —
    which is what makes select-then-hotkey feel instant.
    """
    if session.reader == "wl-paste":
        result = _run(["wl-paste", "--primary", "--no-newline"])
    elif session.reader == "xclip":
        result = _run(["xclip", "-o", "-selection", "primary"])
    elif session.reader == "xsel":
        result = _run(["xsel", "-p", "-o"])
    else:
        return ""
    if result is None or result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", "replace")


def get_clipboard(session: Session) -> str:
    if session.reader == "wl-paste":
        result = _run(["wl-paste", "--no-newline"])
    elif session.reader == "xclip":
        result = _run(["xclip", "-o", "-selection", "clipboard"])
    elif session.reader == "xsel":
        result = _run(["xsel", "-b", "-o"])
    else:
        return ""
    if result is None or result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", "replace")


def set_clipboard(session: Session, text: str) -> bool:
    if session.writer == "wl-copy":
        result = _run(["wl-copy", "--"], stdin=text, capture=False)
    elif session.writer == "xclip":
        result = _run(["xclip", "-i", "-selection", "clipboard"], stdin=text, capture=False)
    elif session.writer == "xsel":
        result = _run(["xsel", "-b", "-i"], stdin=text, capture=False)
    else:
        return False
    return result is not None and result.returncode == 0


# ---------------------------------------------------------------- writing ---

def active_window_class(session: Session) -> Optional[str]:
    """Only knowable on X11. Wayland compositors do not expose this."""
    if session.kind != "x11" or not have("xdotool"):
        return None
    result = _run(["xdotool", "getactivewindow", "getwindowclassname"])
    if result is None or result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip().lower()


def looks_like_terminal(session: Session) -> Optional[bool]:
    cls = active_window_class(session)
    if cls is None:
        return None
    return any(term in cls for term in TERMINAL_CLASSES)


def release_modifiers(session: Session) -> None:
    """Let go of the keys you are still holding.

    You triggered this with Ctrl+Alt+G. Those keys are physically down right
    now, so a naive Ctrl+V would arrive as Ctrl+Alt+Shift+V and do nothing —
    or something unwanted.
    """
    if session.typer == "xdotool":
        # xdotool key --clearmodifiers handles this per-keystroke, but an
        # explicit keyup makes the behaviour identical across window managers.
        _run(["xdotool", "keyup", "ctrl", "alt", "shift", "super"])
    elif session.typer == "ydotool":
        args = [f"{code}:0" for code in MODIFIER_CODES]
        _run(["ydotool", "key"] + args)
    elif session.typer == "wtype":
        for mod in ("ctrl", "alt", "shift", "logo"):
            _run(["wtype", "-m", mod])
    time.sleep(0.12)


def paste(session: Session, shift: bool = False) -> bool:
    """Synthesise Ctrl+V (or Ctrl+Shift+V for terminals)."""
    if session.typer == "xdotool":
        combo = "ctrl+shift+v" if shift else "ctrl+v"
        result = _run(["xdotool", "key", "--clearmodifiers", combo])
        return result is not None and result.returncode == 0

    if session.typer == "ydotool":
        keys = [f"{KEY['leftctrl']}:1"]
        if shift:
            keys.append(f"{KEY['leftshift']}:1")
        keys += [f"{KEY['v']}:1", f"{KEY['v']}:0"]
        if shift:
            keys.append(f"{KEY['leftshift']}:0")
        keys.append(f"{KEY['leftctrl']}:0")
        result = _run(["ydotool", "key"] + keys)
        return result is not None and result.returncode == 0

    if session.typer == "wtype":
        cmd = ["wtype", "-M", "ctrl"]
        if shift:
            cmd += ["-M", "shift"]
        cmd += ["-P", "v", "-p", "v"]
        if shift:
            cmd += ["-m", "shift"]
        cmd += ["-m", "ctrl"]
        result = _run(cmd)
        return result is not None and result.returncode == 0

    return False


def type_text(session: Session, text: str) -> bool:
    """Type the text out key by key instead of pasting.

    Slower and layout-sensitive, but it works in places where Ctrl+V does not
    (some terminals, some Electron apps) and never touches your clipboard.
    """
    if session.typer == "xdotool":
        result = _run(["xdotool", "type", "--clearmodifiers", "--delay", "8", "--", text],
                      timeout=60)
    elif session.typer == "ydotool":
        result = _run(["ydotool", "type", "--key-delay", "8", "--", text], timeout=60)
    elif session.typer == "wtype":
        result = _run(["wtype", "--", text], timeout=60)
    else:
        return False
    return result is not None and result.returncode == 0


def replace_selection(session: Session, text: str, *, restore_clipboard: bool = True,
                      use_typing: bool = False, paste_key: str = "auto") -> str:
    """Put `text` where the selection is. Returns what actually happened.

    "replaced"  — pasted over the selection, you did nothing
    "typed"     — typed out character by character
    "clipboard" — could not paste; text is on the clipboard, press Ctrl+V
    "failed"    — could not even reach the clipboard
    """
    if use_typing and session.can_replace:
        release_modifiers(session)
        return "typed" if type_text(session, text) else "failed"

    previous = get_clipboard(session) if restore_clipboard else ""
    if not set_clipboard(session, text):
        return "failed"

    if not session.can_replace:
        return "clipboard"

    if paste_key == "ctrl+shift+v":
        shift = True
    elif paste_key == "ctrl+v":
        shift = False
    else:
        shift = bool(looks_like_terminal(session))

    release_modifiers(session)
    ok = paste(session, shift=shift)

    if ok and restore_clipboard and previous:
        # Give the target application time to actually read the clipboard
        # before we hand it back; restoring too early pastes the old value.
        time.sleep(0.45)
        set_clipboard(session, previous)

    return "replaced" if ok else "clipboard"


# ------------------------------------------------------------ notifications --

def notify(title: str, body: str = "", urgency: str = "normal", timeout_ms: int = 3500) -> None:
    if not have("notify-send"):
        return
    _run([
        "notify-send",
        "--app-name=QuickAI",
        f"--urgency={urgency}",
        f"--expire-time={timeout_ms}",
        "--icon=accessories-text-editor",
        title,
        body,
    ], timeout=3)
