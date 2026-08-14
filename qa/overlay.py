"""The preview window.

A small always-on-top panel that fills in as the model answers, so you can see
what you are about to paste over your text. Enter accepts, Escape cancels,
Ctrl+R runs it again, Ctrl+C copies without replacing.

The HTTP call runs on a worker thread and pushes fragments through a queue
that Tk drains on its own timer — Tk is not thread-safe, so nothing but the
main thread touches a widget.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, Optional, Tuple

BG = "#0e1116"
BG_2 = "#151a21"
LINE = "#2a323d"
FG = "#e6edf3"
FG_2 = "#9aa7b5"
ACCENT = "#4c9eff"
BAD = "#f85149"


def available() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def review(
    title: str,
    runner: Callable[[Callable[[str], None], Callable[[], bool]], str],
    *,
    can_replace: bool = True,
) -> Tuple[str, str]:
    """Show the panel while `runner` streams.

    `runner(on_delta, should_stop)` must return the finished text.
    Returns (verdict, text) where verdict is accept | copy | cancel.
    """
    import tkinter as tk

    events: "queue.Queue[tuple]" = queue.Queue()
    stop_flag = threading.Event()
    state = {"verdict": "cancel", "text": "", "running": True}

    root = tk.Tk()
    root.title(f"QuickAI · {title}")
    root.configure(bg=BG)
    root.geometry("720x420")
    root.attributes("-topmost", True)
    try:
        root.attributes("-type", "dialog")
    except tk.TclError:
        pass

    header = tk.Frame(root, bg=BG_2, height=34)
    header.pack(fill="x")
    tk.Label(header, text=title, bg=BG_2, fg=FG, font=("sans", 11, "bold")
             ).pack(side="left", padx=12, pady=7)
    status = tk.Label(header, text="thinking…", bg=BG_2, fg=FG_2, font=("sans", 10))
    status.pack(side="right", padx=12)

    body = tk.Text(root, bg=BG, fg=FG, relief="flat", wrap="word",
                   insertbackground=ACCENT, font=("monospace", 11),
                   padx=14, pady=12, highlightthickness=0)
    body.pack(fill="both", expand=True)

    footer = tk.Frame(root, bg=BG_2)
    footer.pack(fill="x")
    hint = "Enter replace · Esc cancel · Ctrl+R again · Ctrl+C copy"
    if not can_replace:
        hint = "Enter copy · Esc cancel · Ctrl+R again"
    tk.Label(footer, text=hint, bg=BG_2, fg=FG_2, font=("sans", 9)
             ).pack(side="left", padx=12, pady=7)

    def finish(verdict):
        state["verdict"] = verdict
        state["text"] = body.get("1.0", "end-1c")
        stop_flag.set()
        root.destroy()

    def start_worker():
        state["running"] = True
        stop_flag.clear()
        body.delete("1.0", "end")
        status.configure(text="thinking…", fg=FG_2)

        def work():
            try:
                text = runner(lambda piece: events.put(("delta", piece)), stop_flag.is_set)
                events.put(("done", text))
            except Exception as exc:  # surfaced in the panel, not a traceback
                events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def drain():
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "delta":
                    body.insert("end", payload)
                    body.see("end")
                    status.configure(text="writing…")
                elif kind == "done":
                    state["running"] = False
                    chars = len(body.get("1.0", "end-1c"))
                    status.configure(text=f"{chars} chars · ready", fg=ACCENT)
                elif kind == "error":
                    state["running"] = False
                    body.insert("end", f"\n\n{payload}")
                    status.configure(text="failed", fg=BAD)
        except queue.Empty:
            pass
        if root.winfo_exists():
            root.after(40, drain)

    root.bind("<Return>", lambda _e: finish("accept" if can_replace else "copy"))
    root.bind("<Escape>", lambda _e: finish("cancel"))
    root.bind("<Control-c>", lambda _e: finish("copy"))
    root.bind("<Control-r>", lambda _e: (stop_flag.set(), start_worker()))
    root.protocol("WM_DELETE_WINDOW", lambda: finish("cancel"))

    start_worker()
    root.after(40, drain)
    root.after(30, lambda: (root.lift(), root.focus_force()))
    root.mainloop()

    return state["verdict"], state["text"].strip()


def show(title: str, text: str) -> Optional[str]:
    """Read-only result window, used by `qa ask`."""
    return review(title, lambda on_delta, stop: (on_delta(text), text)[1],
                  can_replace=True)[0]
