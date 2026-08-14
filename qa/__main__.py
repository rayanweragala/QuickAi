"""qa — run a QuickAI action on the text you have selected, anywhere.

    qa run grammar          fix the selection in place
    qa menu                 pick an action, then fix the selection in place
    qa ask                  ask a question without selecting anything
    qa undo                 recover the text the last run replaced
    qa doctor               explain what this machine can and cannot do
    qa actions              list action ids

Bind `qa menu` to one hotkey and you never open a browser again.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import List, Optional

from . import config as clientcfg
from . import desktop, picker, service

VERSION = "1.1.0"


# ------------------------------------------------------------------ helpers --

def die(message: str, *, notify: bool = True, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    print(f"qa: {message}", file=sys.stderr)
    if notify:
        desktop.notify("QuickAI", message, urgency="critical")
    sys.exit(code)


def gather_input(session: desktop.Session, args) -> str:
    """Where the text comes from, in order of how explicit you were."""
    if args.input:
        return args.input

    if args.stdin:
        return sys.stdin.read()

    # Piped input, but only if data is actually waiting. A hotkey launch gets
    # stdin=/dev/null, and blindly calling read() on an idle pipe would hang
    # the process with no window to show for it.
    if not sys.stdin.isatty():
        try:
            import select
            ready, _, _ = select.select([sys.stdin], [], [], 0.0)
            if ready:
                piped = sys.stdin.read()
                if piped.strip():
                    return piped
        except (OSError, ValueError, UnicodeDecodeError):
            pass
    if args.clipboard:
        return desktop.get_clipboard(session)

    text = desktop.get_selection(session)
    if not text.strip():
        # Nothing highlighted — the clipboard is the obvious second guess.
        text = desktop.get_clipboard(session)
    return text


def pick_action(actions: List[dict], action_id: str) -> dict:
    for action in actions:
        if action["id"] == action_id:
            return action
    known = ", ".join(a["id"] for a in actions)
    die(f"unknown action '{action_id}'. Available: {known}")


def save_undo(original: str, result: str, action_id: str) -> None:
    try:
        path = clientcfg.cache_dir() / "undo.json"
        path.write_text(json.dumps({
            "original": original,
            "result": result,
            "action": action_id,
            "at": time.time(),
        }), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------- run ---

def do_run(args, action_id: Optional[str] = None) -> int:
    cfg = clientcfg.load()
    session = desktop.detect()
    action_id = action_id or args.action

    try:
        actions = service.get_actions()
    except service.ServiceError as exc:
        die(str(exc))

    if action_id == "?":
        chosen = picker.choose(_picker_actions(actions, cfg), cfg["picker"])
        if not chosen:
            return 130
        action = chosen
    else:
        action = pick_action(actions, action_id)

    text = gather_input(session, args)
    if not text.strip():
        die("nothing selected and the clipboard is empty", notify=True)

    limit = int(cfg["max_chars"])
    if len(text) > limit:
        die(f"selection is {len(text)} characters, over the {limit} limit "
            f"(raise max_chars in {clientcfg.path()})")

    preview = args.preview or cfg["always_preview"]
    if preview and not args.stdout:
        return _run_with_preview(session, cfg, action, text, args)

    try:
        result = service.run(action["id"], text, model=args.model)
    except service.ServiceError as exc:
        die(str(exc))

    if not result.strip():
        die("the model returned nothing")

    if args.stdout:
        sys.stdout.write(result)
        if sys.stdout.isatty() and not result.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    return _deliver(session, cfg, args, action, text, result)


def _run_with_preview(session, cfg, action, text, args) -> int:
    from . import overlay

    if not overlay.available():
        die("preview needs tkinter: sudo apt install python3-tk")

    def runner(on_delta, should_stop):
        return service.run(action["id"], text, model=args.model,
                           on_delta=on_delta, should_stop=should_stop)

    verdict, result = overlay.review(action["label"], runner,
                                     can_replace=session.can_replace)
    if verdict == "cancel" or not result:
        return 130
    if verdict == "copy":
        desktop.set_clipboard(session, result)
        desktop.notify("QuickAI", "Copied to clipboard")
        return 0
    return _deliver(session, cfg, args, action, text, result)


def _deliver(session, cfg, args, action, original, result) -> int:
    save_undo(original, result, action["id"])

    status = desktop.replace_selection(
        session,
        result,
        restore_clipboard=cfg["restore_clipboard"],
        use_typing=args.type_out or cfg["use_typing"],
        paste_key=args.paste_key or cfg["paste_key"],
    )

    if status == "failed":
        die("could not reach the clipboard — run `qa doctor`")
    if status == "clipboard":
        desktop.notify("QuickAI · " + action["label"],
                       "Result copied — press Ctrl+V to paste it.\n"
                       "Run `qa doctor` to enable automatic replacing.")
        return 0
    if not args.quiet and cfg["notify_success"]:
        preview_text = result if len(result) < 90 else result[:87] + "…"
        desktop.notify("QuickAI · " + action["label"], preview_text, timeout_ms=2000)
    return 0


def _picker_actions(actions: List[dict], cfg) -> List[dict]:
    wanted = cfg.get("picker_actions") or []
    if not wanted:
        return actions
    by_id = {a["id"]: a for a in actions}
    return [by_id[i] for i in wanted if i in by_id] or actions


# -------------------------------------------------------------------- ask ----

def do_ask(args) -> int:
    cfg = clientcfg.load()
    session = desktop.detect()
    from . import overlay

    question = " ".join(args.question).strip()
    if not question:
        selected = desktop.get_selection(session).strip()
        question = picker.ask_text("Ask QuickAI", "")
        if not question:
            return 130
        if selected and args.with_selection:
            question = f"{question}\n\n{selected}"

    if args.stdout or not overlay.available():
        try:
            result = service.run("ask", question)
        except service.ServiceError as exc:
            die(str(exc))
        sys.stdout.write(result + "\n")
        return 0

    def runner(on_delta, should_stop):
        return service.run("ask", question, on_delta=on_delta, should_stop=should_stop)

    verdict, result = overlay.review("Ask", runner, can_replace=session.can_replace)
    if verdict == "cancel" or not result:
        return 130
    if verdict == "copy":
        desktop.set_clipboard(session, result)
        desktop.notify("QuickAI", "Copied to clipboard")
        return 0

    class _Args:
        quiet = False
        type_out = False
        paste_key = None

    return _deliver(session, cfg, _Args(), {"id": "ask", "label": "Ask"}, question, result)


# ------------------------------------------------------------------- undo ----

def do_undo(_args) -> int:
    session = desktop.detect()
    path = clientcfg.cache_dir() / "undo.json"
    if not path.exists():
        die("nothing to undo yet")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        die("the undo record is unreadable")

    original = saved.get("original", "")
    if not original:
        die("the undo record is empty")

    # We cannot re-select what we replaced, so this hands the original back
    # through the clipboard. In most applications plain Ctrl+Z is quicker,
    # because the replacement went in as a paste.
    if not desktop.set_clipboard(session, original):
        die("could not write to the clipboard")
    desktop.notify("QuickAI · undo",
                   "Your original text is on the clipboard.\n"
                   "Ctrl+Z usually works too — the change was a paste.")
    print(original)
    return 0


# ----------------------------------------------------------------- doctor ----

def do_doctor(_args) -> int:
    session = desktop.detect()
    cfg = clientcfg.load()

    print(f"qa {VERSION}\n")
    print("Session")
    print(f"  display server   {session.kind}")
    print(f"  desktop          {session.desktop or 'unknown'}")
    print(f"  read selection   {session.reader or 'NO — cannot read what you select'}")
    print(f"  set clipboard    {session.writer or 'NO'}")
    print(f"  replace in place {session.typer or 'NO — will fall back to clipboard'}")

    print("\nTools")
    for tool in ("xclip", "xsel", "xdotool", "wl-copy", "wl-paste", "ydotool",
                 "wtype", "rofi", "wofi", "fuzzel", "dmenu", "zenity", "notify-send"):
        print(f"  {'yes' if desktop.have(tool) else ' no'}  {tool}")
    try:
        import tkinter  # noqa: F401
        print("  yes  python3-tk (preview window and fallback picker)")
    except ImportError:
        print("   no  python3-tk (preview window and fallback picker)")

    print("\nService")
    try:
        health = service.get_health()
        llm = health["llm"]
        print(f"  quickai          up at {service.base_url()}")
        print(f"  LLM API          {health['base_url']}")
        if llm["ok"]:
            chosen = health["model"] or f"{llm['models'][0]} (auto on first run)" if llm["models"] else "none"
            print(f"  models           {llm['count']} available, using {chosen}")
        else:
            print(f"  LLM API          UNREACHABLE — {llm['error']}")
    except service.ServiceError as exc:
        print(f"  quickai          DOWN — {exc}")

    print(f"\nClient config      {clientcfg.path()}")
    print(f"  paste key        {cfg['paste_key']}")
    print(f"  restore clip     {'yes' if cfg['restore_clipboard'] else 'no'}")
    print(f"  always preview   {'yes' if cfg['always_preview'] else 'no'}")

    if session.notes:
        print("\nWhat to fix")
        for note in session.notes:
            print(f"  · {note}")
    elif session.can_replace and session.can_read:
        print("\nEverything works: select text anywhere and press your hotkey.")

    if not desktop.have("notify-send"):
        print("  · Install libnotify-bin for error notifications.")

    return 0


def do_actions(args) -> int:
    try:
        actions = service.get_actions()
    except service.ServiceError as exc:
        die(str(exc), notify=False)
    width = max(len(a["id"]) for a in actions)
    for action in actions:
        if args.ids_only:
            print(action["id"])
        else:
            print(f"{action['id']:<{width}}  {action.get('icon', ' ')} {action['label']}")
    return 0


# -------------------------------------------------------------------- cli ----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qa",
        description="Run a QuickAI action on the text you have selected.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 1)[1],
    )
    parser.add_argument("--version", action="version", version=f"qa {VERSION}")
    sub = parser.add_subparsers(dest="command")

    def add_common(p):
        p.add_argument("--preview", action="store_true",
                       help="show the result in a window before replacing")
        p.add_argument("--clipboard", action="store_true",
                       help="use the clipboard instead of the selection")
        p.add_argument("--input", metavar="TEXT", help="use this text instead")
        p.add_argument("--stdin", action="store_true", help="read the text from stdin")
        p.add_argument("--stdout", action="store_true",
                       help="print the result instead of replacing anything")
        p.add_argument("--model", help="override the model for this run")
        p.add_argument("--type", dest="type_out", action="store_true",
                       help="type the result out instead of pasting it")
        p.add_argument("--paste-key", choices=["auto", "ctrl+v", "ctrl+shift+v"],
                       help="force the paste shortcut")
        p.add_argument("--quiet", action="store_true", help="no notifications")

    run_parser = sub.add_parser("run", help="run one action by id")
    run_parser.add_argument("action", help="action id, or ? to open the picker")
    add_common(run_parser)

    menu_parser = sub.add_parser("menu", help="pick an action, then run it")
    add_common(menu_parser)

    ask_parser = sub.add_parser("ask", help="ask a question in a window")
    ask_parser.add_argument("question", nargs="*", help="the question")
    ask_parser.add_argument("--with-selection", action="store_true",
                            help="append the selected text to the question")
    ask_parser.add_argument("--stdout", action="store_true", help="print instead of showing a window")

    sub.add_parser("undo", help="recover the text the last run replaced")
    sub.add_parser("doctor", help="show what works on this machine")

    actions_parser = sub.add_parser("actions", help="list available actions")
    actions_parser.add_argument("--ids-only", action="store_true")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return do_run(args)
    if args.command == "menu":
        return do_run(args, action_id="?")
    if args.command == "ask":
        return do_ask(args)
    if args.command == "undo":
        return do_undo(args)
    if args.command == "doctor":
        return do_doctor(args)
    if args.command == "actions":
        return do_actions(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
