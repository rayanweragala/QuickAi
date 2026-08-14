"""Thin client for the QuickAI service. Standard library only.

The service is already running and already knows your LLM API URL, model, API key
and action prompts — this just asks it to do a thing.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional

DEFAULT_URL = "http://127.0.0.1:7431"


class ServiceError(RuntimeError):
    pass


def base_url() -> str:
    return (os.getenv("QUICKAI_URL") or DEFAULT_URL).rstrip("/")


def _headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("QUICKAI_TOKEN", "").strip()
    if token:
        headers["X-QuickAI-Token"] = token
    return headers


def _request(path: str, method: str = "GET", payload: Optional[dict] = None, timeout: float = 15.0):
    url = base_url() + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except (ValueError, AttributeError):
            pass
        raise ServiceError(f"{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ServiceError(
            f"QuickAI is not running at {base_url()} — start it with "
            f"`systemctl --user start quickai` ({exc.reason})"
        ) from exc
    except OSError as exc:
        raise ServiceError(str(exc)) from exc


def get_actions() -> List[dict]:
    with _request("/api/actions") as response:
        return json.loads(response.read().decode("utf-8"))["actions"]


def get_health() -> dict:
    with _request("/api/health", timeout=25.0) as response:
        return json.loads(response.read().decode("utf-8"))


def run(
    action_id: str,
    text: str,
    *,
    raw: bool = False,
    model: Optional[str] = None,
    history: Optional[List[dict]] = None,
    on_delta: Optional[Callable[[str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    timeout: float = 600.0,
) -> str:
    """Run an action, returning the complete answer.

    `on_delta` is called with each fragment as it arrives, which is what makes
    the preview overlay fill in live rather than appearing all at once.
    """
    payload = {
        "action_id": action_id,
        "input": text,
        "raw": raw,
        "history": history or [],
    }
    if model:
        payload["model"] = model

    parts: List[str] = []
    with _request("/api/run", method="POST", payload=payload, timeout=timeout) as response:
        for line in response:
            if should_stop is not None and should_stop():
                break
            line = line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "delta":
                piece = event.get("text", "")
                parts.append(piece)
                if on_delta:
                    on_delta(piece)
            elif kind == "error":
                raise ServiceError(event.get("message", "unknown error"))

    return "".join(parts)
