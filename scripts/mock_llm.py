"""A fake OpenAI-compatible LLM API for development without a real GPU.

    python scripts/mock_llm.py                 # non-streaming
    python scripts/mock_llm.py --stream        # real SSE streaming
    python scripts/mock_llm.py --port 8123

Then point QuickAI at http://127.0.0.1:8099.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
app.state.force_stream = False

MODELS = ["llama3:8b", "qwen2.5:14b", "nomic-embed-text"]


@app.get("/v1/models")
def models():
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "owned_by": "mock"} for m in MODELS],
    }


def _answer(messages: list[dict]) -> str:
    last = messages[-1]["content"] if messages else ""
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    return (
        f"[mock reply from a fake LLM]\n"
        f"system prompt was {len(system)} chars\n"
        f"you sent {len(last)} chars:\n\n{last[:400]}"
    )


@app.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    text = _answer(messages)
    model = body.get("model") or MODELS[0]

    if body.get("stream") and app.state.force_stream:
        async def gen():
            for word in text.split(" "):
                chunk = {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": word + " "}}],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0.03)
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return JSONResponse(
        {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }
    )


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--stream", action="store_true", help="honour stream=true")
    args = parser.parse_args()

    app.state.force_stream = args.stream
    mode = "streaming" if args.stream else "non-streaming"
    print(f"mock LLM ({mode}) on http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
