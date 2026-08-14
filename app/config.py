"""Persistent configuration.

Everything the user picks in the UI (LLM API URL, model, temperature, custom
actions, theme) lands in a single JSON file outside the repo, so it survives
restarts, upgrades and `git pull`.

    default:  $XDG_CONFIG_HOME/quickai/config.json  (i.e. ~/.config/quickai/)
    override: QUICKAI_CONFIG=/some/where/config.json

Writes are atomic (temp file + rename) so a crash mid-save cannot leave you
with a truncated config.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

from .actions import DEFAULT_ACTIONS

CONFIG_VERSION = 2

_lock = threading.RLock()
_cache: Dict[str, Any] | None = None


def config_path() -> Path:
    override = os.getenv("QUICKAI_CONFIG")
    if override:
        return Path(override).expanduser()
    base = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "quickai" / "config.json"


def defaults() -> Dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        # ---- OpenAI-compatible LLM API ----
        # Base URL of your OpenAI-compatible server, no trailing slash.
        "base_url": os.getenv("QUICKAI_BASE_URL", "http://localhost:8000"),
        # Sent as "Authorization: Bearer <key>" when non-empty. Many
        # local LLM APIs need nothing here.
        "api_key": os.getenv("QUICKAI_API_KEY", ""),
        "models_path": "/v1/models",
        "chat_path": "/v1/chat/completions",
        # ---- generation ----
        "model": os.getenv("QUICKAI_MODEL", ""),
        "temperature": 0.3,
        "max_tokens": None,
        "request_timeout": 300,
        # Merged into every upstream request body for provider-specific fields.
        "extra_body": {},
        # ---- behaviour ----
        "actions": copy.deepcopy(DEFAULT_ACTIONS),
        "ui": {
            "theme": "dark",
            "last_action": "grammar",
            "auto_copy": False,
            "font_size": 15,
        },
    }


def _merge(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Recursive merge, used both for migrations and for PATCH-style updates."""
    out = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(force: bool = False) -> Dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None and not force:
            return copy.deepcopy(_cache)

        path = config_path()
        data: Dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except (json.JSONDecodeError, OSError):
                # Never let a corrupt file take the app down: keep a copy and
                # fall back to defaults.
                try:
                    path.rename(path.with_suffix(".json.broken"))
                except OSError:
                    pass
                data = {}

        merged = _merge(defaults(), data)
        # A config with no actions at all would leave a dead UI.
        if not merged.get("actions"):
            merged["actions"] = copy.deepcopy(DEFAULT_ACTIONS)
        # v2 adds built-ins without overwriting prompts the user customized.
        if data.get("version", 0) < 2:
            action_ids = {action.get("id") for action in merged["actions"]}
            merged["actions"].extend(
                copy.deepcopy(action)
                for action in DEFAULT_ACTIONS
                if action["id"] not in action_ids
            )
        merged["version"] = CONFIG_VERSION
        _cache = merged
        if not path.exists() or data.get("version", 0) < CONFIG_VERSION:
            _write(merged)
        return copy.deepcopy(merged)


def _write(cfg: Dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)  # it can hold an API key
    except OSError:
        pass


def save(cfg: Dict[str, Any]) -> Dict[str, Any]:
    global _cache
    with _lock:
        cfg = dict(cfg)
        cfg["version"] = CONFIG_VERSION
        _write(cfg)
        _cache = cfg
        return copy.deepcopy(cfg)


def update(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge `patch` into the stored config and persist it."""
    with _lock:
        return save(_merge(load(), patch))


def reset_actions() -> Dict[str, Any]:
    """Restore the shipped action set, keeping the user's own actions."""
    with _lock:
        cfg = load()
        custom = [a for a in cfg.get("actions", []) if not a.get("builtin")]
        cfg["actions"] = copy.deepcopy(DEFAULT_ACTIONS) + custom
        return save(cfg)


def redacted(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Config safe to hand to the browser: the key itself never leaves disk."""
    out = copy.deepcopy(cfg)
    out["has_api_key"] = bool(out.get("api_key"))
    out.pop("api_key", None)
    return out
