"""The action menu.

One hotkey should be enough for all 17 actions, so pressing it opens a filter
list: type two letters, press Enter. If you already have rofi, wofi, fuzzel or
dmenu installed we use it, because it will match the rest of your desktop and
appear instantly. Otherwise we draw a small Tk window that behaves the same
way.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional

PROMPT = "QuickAI"


def _backends() -> List[str]:
    return [name for name in ("rofi", "wofi", "fuzzel", "dmenu", "zenity")
            if shutil.which(name)]


def choose(actions: List[dict], preferred: str = "auto") -> Optional[dict]:
    """Show the menu; return the chosen action dict, or None if cancelled."""
    if not actions:
        return None

    # Numbering makes the first few actions selectable with a single keypress.
    lines = [
        f"{index + 1}. {action['label']}"
        for index, action in enumerate(actions)
    ]

    order = _backends()
    if preferred != "auto":
        order = [preferred] if preferred != "tk" else []

    for backend in order:
        picked = _run_dmenu(backend, lines)
        if picked is None:      # cancelled
            return None
        if picked == "":        # backend unavailable, try the next
            continue
        for line, action in zip(lines, actions):
            if line.strip() == picked.strip():
                return action
        return None

    return _tk_choose(actions, lines)


def _run_dmenu(backend: str, lines: List[str]) -> Optional[str]:
    """Returns the chosen line, "" if the backend could not run, None if the
    user pressed Escape."""
    if backend == "rofi":
        cmd = ["rofi", "-dmenu", "-i", "-p", PROMPT, "-lines", str(min(len(lines), 12))]
    elif backend == "wofi":
        cmd = ["wofi", "--dmenu", "-i", "-p", PROMPT]
    elif backend == "fuzzel":
        cmd = ["fuzzel", "--dmenu", "--prompt", PROMPT + " "]
    elif backend == "dmenu":
        cmd = ["dmenu", "-i", "-l", str(min(len(lines), 12)), "-p", PROMPT]
    elif backend == "zenity":
        cmd = ["zenity", "--list", "--title", PROMPT, "--column", "Action",
               "--height", "460", "--width", "360"] + lines
    else:
        return ""

    try:
        if backend == "zenity":
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=180)
        else:
            result = subprocess.run(cmd, input="\n".join(lines).encode("utf-8"),
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=180)
    except (OSError, subprocess.SubprocessError):
        return ""

    choice = result.stdout.decode("utf-8", "replace").strip()
    if result.returncode != 0 or not choice:
        return None
    return choice


def _tk_choose(actions: List[dict], lines: List[str]) -> Optional[dict]:
    try:
        import tkinter as tk
    except ImportError:
        return None

    chosen = {"action": None}

    root = tk.Tk()
    root.title("QuickAI")
    root.configure(bg="#151a21")
    root.attributes("-topmost", True)
    root.geometry("420x420")
    try:
        root.attributes("-type", "dialog")
    except tk.TclError:
        pass

    entry = tk.Entry(root, bg="#0e1116", fg="#e6edf3", insertbackground="#4c9eff",
                     relief="flat", font=("sans", 13))
    entry.pack(fill="x", padx=10, pady=(10, 6), ipady=6)

    listbox = tk.Listbox(root, bg="#0e1116", fg="#e6edf3", relief="flat",
                         selectbackground="#4c9eff", selectforeground="#07121f",
                         highlightthickness=0, font=("sans", 12), activestyle="none")
    listbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    visible: List[int] = []

    def refill(*_args):
        needle = entry.get().lower().strip()
        listbox.delete(0, "end")
        visible.clear()
        for index, line in enumerate(lines):
            if not needle or needle in line.lower():
                listbox.insert("end", "  " + line)
                visible.append(index)
        if visible:
            listbox.selection_clear(0, "end")
            listbox.selection_set(0)
            listbox.activate(0)

    def accept(*_args):
        selection = listbox.curselection()
        if not selection and visible:
            selection = (0,)
        if selection:
            chosen["action"] = actions[visible[selection[0]]]
        root.destroy()

    def move(delta):
        if not visible:
            return "break"
        current = listbox.curselection()
        index = (current[0] if current else 0) + delta
        index = max(0, min(len(visible) - 1, index))
        listbox.selection_clear(0, "end")
        listbox.selection_set(index)
        listbox.activate(index)
        listbox.see(index)
        return "break"

    def digit(event):
        if entry.get():          # they are filtering, let the digit through
            return None
        wanted = int(event.char)
        if wanted <= len(actions):
            chosen["action"] = actions[wanted - 1]
            root.destroy()
        return "break"

    entry.bind("<KeyRelease>", refill)
    entry.bind("<Return>", accept)
    entry.bind("<Escape>", lambda _e: root.destroy())
    entry.bind("<Down>", lambda _e: move(1))
    entry.bind("<Up>", lambda _e: move(-1))
    for number in range(1, 10):
        entry.bind(str(number), digit)
    listbox.bind("<Double-Button-1>", accept)
    listbox.bind("<Return>", accept)

    refill()
    root.after(30, lambda: (root.lift(), root.focus_force(), entry.focus_set()))
    root.mainloop()
    return chosen["action"]


def ask_text(title: str = "Ask QuickAI", prefill: str = "") -> Optional[str]:
    """A one-line input box, for asking a question with nothing selected."""
    if shutil.which("rofi"):
        try:
            result = subprocess.run(
                ["rofi", "-dmenu", "-p", title, "-lines", "0"],
                input=prefill.encode("utf-8"), stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=300)
            text = result.stdout.decode("utf-8", "replace").strip()
            return text or None
        except (OSError, subprocess.SubprocessError):
            pass

    try:
        import tkinter as tk
    except ImportError:
        return None

    value = {"text": None}
    root = tk.Tk()
    root.title(title)
    root.configure(bg="#151a21")
    root.attributes("-topmost", True)
    root.geometry("560x120")

    tk.Label(root, text=title, bg="#151a21", fg="#9aa7b5",
             font=("sans", 10)).pack(anchor="w", padx=12, pady=(10, 2))
    entry = tk.Entry(root, bg="#0e1116", fg="#e6edf3", insertbackground="#4c9eff",
                     relief="flat", font=("sans", 13))
    entry.pack(fill="x", padx=12, ipady=7)
    entry.insert(0, prefill)

    def accept(*_args):
        value["text"] = entry.get().strip() or None
        root.destroy()

    entry.bind("<Return>", accept)
    entry.bind("<Escape>", lambda _e: root.destroy())
    root.after(30, lambda: (root.lift(), root.focus_force(), entry.focus_set()))
    root.mainloop()
    return value["text"]
