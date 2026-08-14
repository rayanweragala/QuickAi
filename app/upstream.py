"""Talks to an OpenAI-compatible LLM API.

Two things worth knowing:

1. This module is why the browser never touches your LLM API directly. The page is
   same-origin with this service, so there is no CORS to configure and no mixed
   content problem when the LLM API is on https.

2. It asks for `stream: true` but does not assume it gets it. Plenty of
   local servers (including FastAPI wrappers that hardcode
   `"stream": False` when proxying to Ollama) answer a streaming request with a
   single JSON body. `stream_chat` sniffs the response and handles both, so you
   get live tokens where they are available and a correct answer where they are
   not.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx


class UpstreamError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _base(cfg: Dict[str, Any]) -> str:
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        raise UpstreamError("No LLM API URL configured. Open Settings and set one.", 400)
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    return base


def _url(cfg: Dict[str, Any], key: str, fallback: str) -> str:
    path = (cfg.get(key) or fallback).strip()
    if not path.startswith("/"):
        path = "/" + path
    return _base(cfg) + path


def _headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = (cfg.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _timeout(cfg: Dict[str, Any]) -> httpx.Timeout:
    total = float(cfg.get("request_timeout") or 300)
    # Generous read timeout (a cold model load is slow), quick connect timeout
    # so an unreachable LLM API fails fast instead of hanging the UI.
    return httpx.Timeout(total, connect=10.0)


# ---------------------------------------------------------------- models ----

def _parse_models(payload: Any) -> List[str]:
    """Accept common model-list shapes returned by OpenAI-compatible APIs."""
    items: Any = None
    if isinstance(payload, dict):
        for key in ("data", "models", "results"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
    elif isinstance(payload, list):
        items = payload
    if items is None:
        return []

    names: List[str] = []
    for item in items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            for key in ("id", "name", "model"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    names.append(value)
                    break
    # de-duplicate, preserve order
    seen: set = set()
    return [n for n in names if not (n in seen or seen.add(n))]


async def list_models(cfg: Dict[str, Any]) -> List[str]:
    url = _url(cfg, "models_path", "/v1/models")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
            resp = await client.get(url, headers=_headers(cfg))
    except httpx.HTTPError as exc:
        raise UpstreamError(f"Cannot reach {url}: {exc}") from exc

    if resp.status_code >= 400:
        raise UpstreamError(
            f"{url} returned {resp.status_code}: {resp.text[:300]}", resp.status_code
        )
    try:
        return _parse_models(resp.json())
    except ValueError as exc:
        raise UpstreamError(f"{url} did not return JSON") from exc


async def health(cfg: Dict[str, Any]) -> Dict[str, Any]:
    try:
        models = await list_models(cfg)
    except UpstreamError as exc:
        return {"ok": False, "error": str(exc), "models": []}
    return {"ok": True, "models": models, "count": len(models)}


# ------------------------------------------------------------------ chat ----

def _extract_text(payload: Any) -> str:
    """Pull assistant text from common OpenAI-compatible response shapes."""
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message") or choice.get("delta")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):  # content-block style
                    return "".join(
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict)
                    )
            if isinstance(choice.get("text"), str):
                return choice["text"]

    # Non-OpenAI shapes seen in the wild / in this project's own /chat route.
    for key in ("answer", "response", "content", "output_text", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value

    if isinstance(payload.get("message"), dict):
        content = payload["message"].get("content")
        if isinstance(content, str):
            return content
    return ""


def build_payload(
    cfg: Dict[str, Any],
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    stream: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model or cfg.get("model") or "",
        "messages": messages,
        "stream": stream,
    }
    temp = cfg.get("temperature") if temperature is None else temperature
    if temp is not None:
        payload["temperature"] = float(temp)
    if cfg.get("max_tokens"):
        payload["max_tokens"] = int(cfg["max_tokens"])
    extra = cfg.get("extra_body")
    if isinstance(extra, dict):
        payload.update(extra)
    return payload


async def stream_chat(
    cfg: Dict[str, Any],
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
) -> AsyncIterator[str]:
    """Yield answer fragments. One big fragment if the LLM API cannot stream."""
    url = _url(cfg, "chat_path", "/v1/chat/completions")
    payload = build_payload(cfg, messages, model, temperature, stream=True)
    headers = dict(_headers(cfg))
    headers["Accept"] = "text/event-stream, application/json"

    try:
        async with httpx.AsyncClient(timeout=_timeout(cfg)) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise UpstreamError(
                        f"LLM API returned {resp.status_code}: {body[:400]}",
                        resp.status_code,
                    )

                ctype = resp.headers.get("content-type", "")
                if "text/event-stream" in ctype:
                    async for piece in _iter_sse(resp):
                        yield piece
                    return

                # Non-streaming answer: read it all, emit once.
                raw = (await resp.aread()).decode("utf-8", "replace").strip()
                if not raw:
                    return
                try:
                    text = _extract_text(json.loads(raw))
                except json.JSONDecodeError:
                    # Some servers stream SSE while labelling it text/plain.
                    text = _text_from_sse_blob(raw) or raw
                if text:
                    yield text
    except UpstreamError:
        raise
    except httpx.HTTPError as exc:
        raise UpstreamError(f"Cannot reach {url}: {exc}") from exc


async def _iter_sse(resp: httpx.Response) -> AsyncIterator[str]:
    async for line in resp.aiter_lines():
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            if data == "[DONE]":
                return
            continue
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk, dict) and chunk.get("error"):
            raise UpstreamError(str(chunk["error"])[:400])
        piece = _extract_text(chunk)
        if piece:
            yield piece


def _text_from_sse_blob(raw: str) -> str:
    """Last-ditch: a whole SSE stream delivered as one mislabelled body."""
    out: List[str] = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                out.append(_extract_text(json.loads(data)))
            except json.JSONDecodeError:
                continue
    return "".join(out)
