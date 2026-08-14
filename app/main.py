"""QuickAI — a one-page front end for any OpenAI-compatible LLM.

Run it:      python -m app.main          (or ./run.sh)
Then open:   http://127.0.0.1:7431

The browser only talks to this service; this service talks to your LLM API.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config as cfgmod
from . import upstream
from .actions import DEFAULT_ACTIONS

__version__ = "1.1.0"

logging.basicConfig(
    level=os.getenv("QUICKAI_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-7s %(message)s",
)
log = logging.getLogger("quickai")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
HOST = os.getenv("QUICKAI_HOST", "127.0.0.1")
PORT = int(os.getenv("QUICKAI_PORT", "7431"))
TOKEN = os.getenv("QUICKAI_TOKEN", "").strip()

app = FastAPI(title="QuickAI", version=__version__, docs_url=None, redoc_url=None)


# ------------------------------------------------------------------ auth ----
# Off by default: bound to localhost there is nothing to protect against. Set
# QUICKAI_TOKEN when you bind to 0.0.0.0 so the LAN cannot use your LLM.

@app.middleware("http")
async def token_gate(request: Request, call_next):
    if not TOKEN:
        return await call_next(request)

    supplied = (
        request.headers.get("x-quickai-token")
        or request.query_params.get("token")
        or request.cookies.get("quickai_token")
        or ""
    )
    if secrets.compare_digest(supplied, TOKEN):
        response = await call_next(request)
        if request.query_params.get("token"):
            response.set_cookie(
                "quickai_token", TOKEN, httponly=True, samesite="lax", max_age=31536000
            )
        return response

    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Bad or missing token"}, status_code=401)
    return JSONResponse(
        {"detail": "Add ?token=YOUR_TOKEN to the URL once to unlock."}, status_code=401
    )


# --------------------------------------------------------------- schemas ----

class ConfigPatch(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    models_path: Optional[str] = None
    chat_path: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    request_timeout: Optional[int] = None
    extra_body: Optional[Dict[str, Any]] = None
    ui: Optional[Dict[str, Any]] = None


class Action(BaseModel):
    id: str = ""
    label: str = "Untitled"
    icon: str = "AI"
    group: str = "Custom"
    system: str = ""
    template: str = "{input}"
    temperature: Optional[float] = None
    builtin: bool = False


class ActionList(BaseModel):
    actions: List[Action]


class Turn(BaseModel):
    role: str
    content: str


class RunRequest(BaseModel):
    action_id: str = "ask"
    input: str = ""
    model: Optional[str] = None
    temperature: Optional[float] = None
    # Prior turns, so "ask a follow-up about this answer" works.
    history: List[Turn] = Field(default_factory=list)
    # True for follow-ups: send `input` verbatim instead of through the
    # action's template (you don't want "Correct this text: shorter").
    raw: bool = False


# ----------------------------------------------------------------- utils ----

def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "action"


def find_action(cfg: Dict[str, Any], action_id: str) -> Dict[str, Any]:
    for action in cfg.get("actions", []):
        if action.get("id") == action_id:
            return action
    raise HTTPException(status_code=404, detail=f"Unknown action '{action_id}'")


def render(template: str, text: str) -> str:
    template = template or "{input}"
    if "{input}" in template:
        return template.replace("{input}", text)
    return f"{template}\n\n{text}".strip()


def sse(event: Dict[str, Any]) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


# ------------------------------------------------------------------ API -----

@app.get("/api/health")
async def api_health():
    cfg = cfgmod.load()
    result = await upstream.health(cfg)
    return {
        "app": "quickai",
        "version": __version__,
        "base_url": cfg.get("base_url"),
        "model": cfg.get("model"),
        "llm": result,
    }


@app.get("/api/config")
async def api_get_config():
    return cfgmod.redacted(cfgmod.load())


@app.put("/api/config")
async def api_put_config(patch: ConfigPatch):
    data = {k: v for k, v in patch.model_dump().items() if v is not None}
    if "base_url" in data:
        data["base_url"] = data["base_url"].strip().rstrip("/")
    # An empty string means "clear the key"; absent means "leave it alone".
    if patch.api_key is not None:
        data["api_key"] = patch.api_key.strip()
    cfg = cfgmod.update(data)
    log.info("config updated (base_url=%s model=%s)", cfg.get("base_url"), cfg.get("model"))
    return cfgmod.redacted(cfg)


@app.get("/api/models")
async def api_models(refresh: bool = False):
    cfg = cfgmod.load(force=refresh)
    try:
        models = await upstream.list_models(cfg)
    except upstream.UpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # If nothing is selected yet, or the saved pick vanished from the LLM API,
    # fall back to the first available model and remember it.
    current = cfg.get("model") or ""
    if models and current not in models:
        cfgmod.update({"model": models[0]})
        current = models[0]
    return {"models": models, "selected": current}


@app.get("/api/actions")
async def api_get_actions():
    return {"actions": cfgmod.load().get("actions", [])}


@app.put("/api/actions")
async def api_put_actions(body: ActionList):
    seen: set = set()
    cleaned: List[Dict[str, Any]] = []
    for action in body.actions:
        item = action.model_dump()
        item["id"] = item["id"].strip() or slugify(item["label"])
        while item["id"] in seen:
            item["id"] += "-2"
        seen.add(item["id"])
        cleaned.append(item)
    if not cleaned:
        raise HTTPException(status_code=400, detail="At least one action is required")
    cfg = cfgmod.update({"actions": cleaned})
    return {"actions": cfg["actions"]}


@app.get("/api/actions/defaults")
async def api_default_actions():
    return {"actions": DEFAULT_ACTIONS}


@app.post("/api/actions/reset")
async def api_reset_actions():
    return {"actions": cfgmod.reset_actions()["actions"]}


@app.post("/api/run")
async def api_run(req: RunRequest):
    cfg = cfgmod.load()
    text = (req.input or "").strip()
    action = find_action(cfg, req.action_id)

    if not text and not req.history:
        raise HTTPException(status_code=400, detail="Nothing to send")

    messages: List[Dict[str, str]] = []
    if action.get("system"):
        messages.append({"role": "system", "content": action["system"]})
    for turn in req.history:
        if turn.role in ("user", "assistant") and turn.content:
            messages.append({"role": turn.role, "content": turn.content})
    prompt = text if req.raw else render(action.get("template", ""), text)
    messages.append({"role": "user", "content": prompt})

    temperature = req.temperature
    if temperature is None:
        temperature = action.get("temperature")

    model = req.model or cfg.get("model") or None
    if not model:
        # The desktop client can be the first thing you ever run, in which case
        # nobody has picked a model yet. Choose one rather than sending "".
        try:
            available = await upstream.list_models(cfg)
        except upstream.UpstreamError:
            available = []
        if available:
            model = available[0]
            cfgmod.update({"model": model})
            log.info("auto-selected model %s", model)

    # Remember the last action used so a reload feels like you never left.
    cfgmod.update({"ui": {"last_action": action["id"]}})

    async def body() -> AsyncIterator[str]:
        # `prompt` goes back to the client so follow-up turns can replay the
        # exact user message the model saw.
        yield sse(
            {"type": "start", "action": action["id"], "model": model, "prompt": prompt}
        )
        chars = 0
        try:
            async for piece in upstream.stream_chat(cfg, messages, model, temperature):
                chars += len(piece)
                yield sse({"type": "delta", "text": piece})
        except upstream.UpstreamError as exc:
            log.warning("run failed: %s", exc)
            yield sse({"type": "error", "message": str(exc)})
            return
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("unexpected failure")
            yield sse({"type": "error", "message": f"Unexpected error: {exc}"})
            return
        if chars == 0:
            yield sse({"type": "error", "message": "The LLM returned an empty response."})
            return
        yield sse({"type": "done", "chars": chars})

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------- UI -----

if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index(request: Request):
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse({"detail": "web/index.html is missing"}, status_code=500)
    if TOKEN and request.query_params.get("token"):
        # Drop the token from the address bar once the cookie is set.
        response = RedirectResponse("/")
        response.set_cookie(
            "quickai_token", TOKEN, httponly=True, samesite="lax", max_age=31536000
        )
        return response
    return FileResponse(index_file, headers={"Cache-Control": "no-store"})


@app.get("/favicon.ico")
async def favicon():
    icon = WEB_DIR / "favicon.svg"
    if icon.exists():
        return FileResponse(icon, media_type="image/svg+xml")
    return JSONResponse({}, status_code=404)


def main() -> None:
    import uvicorn

    cfg = cfgmod.load()
    log.info("QuickAI %s", __version__)
    log.info("config    %s", cfgmod.config_path())
    log.info("LLM API   %s", cfg.get("base_url"))
    log.info("listening http://%s:%s", HOST, PORT)
    if HOST not in ("127.0.0.1", "localhost", "::1") and not TOKEN:
        log.warning(
            "Bound to %s with no QUICKAI_TOKEN set — anyone on this network can "
            "use your LLM.",
            HOST,
        )
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
