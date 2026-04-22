#!/usr/bin/env python3
# --------------------------------------------------
# Copyright
# --------------------------------------------------
#
# Tech Aarvam
# Copyright (c) 2026 Tech Aarvam.
# Primary authors: Ram (Ramasubramanian B), Claude Code
#
"""
OpenRouter Free Programming Models Proxy

Discovers free models tagged as "Programming" on OpenRouter every 24 hours.
Exposes a single virtual model name "current-free-model" on a local port.
Automatically rotates to the next model when one is overloaded or down.

Usage:
    python3 openrouter_free_proxy.py --api-key sk-or-v1-... --port 8200
    # or set OPENROUTER_API_KEY env var
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_FRONTEND = "https://openrouter.ai/api/frontend"
CACHE_FILE = Path(__file__).parent / "openrouter_free_models_cache.json"
REFRESH_HOURS = 24
VIRTUAL_MODEL = "current-free-model"
DEFAULT_PORT = 8200

# HTTP status codes that indicate a model is overloaded / unavailable
FAILOVER_CODES = {429, 502, 503, 504, 529}

# How long a failing model stays out of rotation before being retried
COOLDOWN_SECONDS = 300  # 5 minutes

# Meta-routers and non-text-generation models to exclude even if free+programming
EXCLUDE_IDS = {"openrouter/free", "google/lyria-3-pro-preview", "google/lyria-3-clip-preview"}

# Regex to extract parameter counts (e.g. "120B", "480B", "7.4B") from model text.
# We take the maximum value found — for MoE models that's the total param count.
_PARAM_RE = re.compile(r'(\d+(?:\.\d+)?)\s*[Bb](?!ytes)', re.IGNORECASE)

LARGE_MODEL_THRESHOLD_B = 100  # models above this (total params) get priority

log = logging.getLogger("or-free-proxy")

# Set by main() before uvicorn starts
OPENROUTER_API_KEY: str = ""

# ---------------------------------------------------------------------------
# Parameter count helpers
# ---------------------------------------------------------------------------

def _max_params_b(model: dict) -> float:
    """
    Extract the largest parameter count (billions) from model id, name, description.
    For MoE models the maximum value is always the total param count.
    Returns 0.0 if nothing parseable is found.
    """
    text = (
        f"{model.get('id', '')} "
        f"{model.get('name', '')} "
        f"{model.get('description', '')[:400]}"
    )
    hits = [float(v) for v in _PARAM_RE.findall(text) if float(v) >= 1.0]
    return max(hits) if hits else 0.0


def _is_large(model: dict) -> bool:
    return _max_params_b(model) > LARGE_MODEL_THRESHOLD_B


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------

async def _fetch_models() -> list[dict]:
    """
    Two-pass discovery:
    1. Frontend API  → slugs that carry the "Programming" category tag
    2. v1 API        → pricing + supported_parameters for every model
    Intersection: free + programming + tool-call support, excluding meta-routers.
    """
    async with httpx.AsyncClient(timeout=30) as c:
        # Pass 1: programming-tagged slugs (no auth needed)
        r1 = await c.get(
            f"{OPENROUTER_FRONTEND}/models",
            params={"category": "programming"},
            headers={"User-Agent": "aarvam-free-proxy/1.0"},
        )
        r1.raise_for_status()
        prog_slugs: set[str] = set()
        for m in r1.json().get("data", []):
            slug = m.get("slug", "")
            if slug:
                prog_slugs.add(slug)
                prog_slugs.add(slug.replace(":free", ""))  # match both variants

        # Pass 2: full model list with pricing
        r2 = await c.get(
            f"{OPENROUTER_BASE}/models",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        )
        r2.raise_for_status()

    result = []
    for m in r2.json().get("data", []):
        mid = m.get("id", "")
        if mid in EXCLUDE_IDS:
            continue
        # Free: prompt price == "0"
        pricing = m.get("pricing", {})
        try:
            if float(pricing.get("prompt") or "1") != 0.0:
                continue
        except (ValueError, TypeError):
            continue
        # Programming category (check both slug forms)
        base = mid.replace(":free", "")
        if mid not in prog_slugs and base not in prog_slugs:
            continue
        # Tool-call support required for coding agent use
        sp = m.get("supported_parameters", [])
        if "tools" not in sp and "tool_choice" not in sp:
            continue
        result.append(m)

    # Sort: >100B models first (by param count desc), then smaller models.
    # Within each tier, prefer larger context windows.
    result.sort(key=lambda m: (
        0 if _is_large(m) else 1,       # large tier first
        -_max_params_b(m),               # biggest model within tier first
        -int(m.get("context_length") or 0),
        m.get("id", ""),
    ))

    large = [m for m in result if _is_large(m)]
    small = [m for m in result if not _is_large(m)]
    log.info("Discovered %d free programming models (%d >%dB, %d smaller):",
             len(result), len(large), LARGE_MODEL_THRESHOLD_B, len(small))
    for m in result:
        params = _max_params_b(m)
        tag = f">100B {params:.0f}B" if _is_large(m) else f"      {params:.0f}B"
        log.info("  [%s]  %-55s  ctx=%s", tag, m["id"], m.get("context_length", "?"))
    return result

# ---------------------------------------------------------------------------
# Model registry with daily refresh
# ---------------------------------------------------------------------------

class ModelRegistry:
    def __init__(self):
        self._models: list[dict] = []
        self._lock = asyncio.Lock()
        self._last_refresh: datetime = datetime.min
        # model_id → datetime when cooldown expires
        self._cooldowns: dict[str, datetime] = {}

    def mark_failed(self, model_id: str) -> None:
        until = datetime.now() + timedelta(seconds=COOLDOWN_SECONDS)
        self._cooldowns[model_id] = until
        log.warning("[COOLDOWN] %s benched until %s", model_id, until.strftime("%H:%M:%S"))

    def mark_ok(self, model_id: str) -> None:
        if model_id in self._cooldowns:
            del self._cooldowns[model_id]
            log.info("[RECOVERED] %s back in active rotation", model_id)

    def active_snapshot(self) -> list[dict]:
        """
        Returns models in priority order. Cooling-down models are moved to the
        back (still tried as last resort) rather than excluded entirely, so the
        proxy never hard-fails when everything is temporarily overloaded.
        Expired cooldowns are cleared here.
        """
        now = datetime.now()
        # Expire old cooldowns and log recovery
        recovered = [mid for mid, until in self._cooldowns.items() if until <= now]
        for mid in recovered:
            del self._cooldowns[mid]
            log.info("[RECOVERED] %s cooldown expired, re-entering rotation", mid)

        active, cooling = [], []
        for m in self._models:
            (cooling if m["id"] in self._cooldowns else active).append(m)
        return active + cooling

    def cooldown_status(self) -> list[dict]:
        now = datetime.now()
        return [
            {"id": mid, "seconds_remaining": max(0, int((until - now).total_seconds()))}
            for mid, until in self._cooldowns.items()
        ]

    def snapshot(self) -> list[dict]:
        return list(self._models)

    def current(self) -> dict | None:
        active = self.active_snapshot()
        return active[0] if active else None

    async def refresh(self, force: bool = False) -> None:
        async with self._lock:
            if not force:
                age = datetime.now() - self._last_refresh
                if age < timedelta(hours=REFRESH_HOURS):
                    return
            try:
                models = await _fetch_models()
                if models:
                    self._models = models
                    self._last_refresh = datetime.now()
                    _save_cache(models)
                else:
                    log.warning("Fetch returned 0 models; keeping existing list")
            except Exception as exc:
                log.warning("Refresh failed (%s); loading cache", exc)
                cached = _load_cache()
                if cached:
                    self._models = cached


registry = ModelRegistry()


def _save_cache(models: list[dict]) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(
            {"refreshed": datetime.now().isoformat(), "models": models}, indent=2
        ))
    except Exception as e:
        log.warning("Cache write failed: %s", e)


def _load_cache() -> list[dict]:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            log.info("Loaded %d models from cache (refreshed %s)",
                     len(data.get("models", [])), data.get("refreshed"))
            return data.get("models", [])
    except Exception as e:
        log.warning("Cache read failed: %s", e)
    return []

# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _or_headers(incoming: dict) -> dict:
    h = {k: v for k, v in incoming.items()
         if k.lower() not in ("host", "content-length", "authorization")}
    h["Authorization"] = f"Bearer {OPENROUTER_API_KEY}"
    h["HTTP-Referer"] = "http://localhost"
    h["X-Title"] = "aarvam-free-proxy"
    return h


def _or_body(model_id: str, req: dict) -> bytes:
    return json.dumps({**req, "model": model_id}).encode()


def _is_overloaded_json(data: dict) -> bool:
    err = data.get("error", {})
    code = int(err.get("code", 0))
    msg = str(err.get("message", "")).lower()
    return (
        code in (429, 503, 529)
        or "overload" in msg
        or "rate limit" in msg
        or "no endpoints" in msg
        or "quota" in msg
    )

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="OpenRouter Free Programming Proxy")


@app.on_event("startup")
async def _startup():
    cached = _load_cache()
    if cached:
        registry._models = cached
    asyncio.create_task(_refresh_loop())


async def _refresh_loop():
    await registry.refresh(force=True)
    while True:
        await asyncio.sleep(REFRESH_HOURS * 3600)
        await registry.refresh(force=True)


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

@app.get("/status")
async def status():
    all_models = registry.snapshot()
    cooling = registry.cooldown_status()
    cooling_ids = {c["id"] for c in cooling}
    return {
        "virtual_model": VIRTUAL_MODEL,
        "current_model": (registry.current() or {}).get("id"),
        "total_models": len(all_models),
        "active_models": len(all_models) - len(cooling_ids),
        "cooling_down": cooling,
        "last_refresh": registry._last_refresh.isoformat(),
        "next_refresh_in_hours": round(
            max(0, REFRESH_HOURS - (datetime.now() - registry._last_refresh).total_seconds() / 3600), 1
        ),
        "models": [
            {
                "id": m["id"],
                "params_b": _max_params_b(m) or None,
                "large": _is_large(m),
                "context_length": m.get("context_length"),
                "status": "cooling" if m["id"] in cooling_ids else "active",
            }
            for m in all_models
        ],
    }


# ---------------------------------------------------------------------------
# Models list endpoint
# ---------------------------------------------------------------------------

@app.get("/v1/models")
async def list_models():
    models = registry.snapshot()
    items = []
    current = registry.current()
    items.append({
        "id": VIRTUAL_MODEL,
        "object": "model",
        "name": f"Current Free Model → {current['id'] if current else 'none'}",
        "context_length": current.get("context_length") if current else None,
    })
    for m in models:
        items.append({"id": m["id"], "object": "model",
                      "name": m.get("name", m["id"]),
                      "context_length": m.get("context_length")})
    return {"object": "list", "data": items}


# ---------------------------------------------------------------------------
# Chat completions with failover
# ---------------------------------------------------------------------------

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    raw = await request.body()
    incoming_hdrs = dict(request.headers)
    try:
        req = json.loads(raw)
    except Exception:
        return Response(content=raw, status_code=400)

    model_name = req.get("model", "")
    streaming = req.get("stream", False)

    if model_name != VIRTUAL_MODEL:
        # Passthrough for explicit model names
        return await _passthrough(req, incoming_hdrs)

    models = registry.snapshot()
    if not models:
        return JSONResponse(
            {"error": {"message": "No free programming models discovered yet", "code": 503}},
            status_code=503,
        )

    models = registry.active_snapshot()
    log.info("[REQ] virtual model, stream=%s, candidates=%d", streaming, len(models))

    if streaming:
        return StreamingResponse(
            _streaming_failover(req, incoming_hdrs, models),
            media_type="text/event-stream",
        )
    return await _blocking_failover(req, incoming_hdrs, models)


def _rotation_note_chunk(failed: list[str], winner: str) -> bytes:
    """One SSE content delta injected before the real response when rotation occurred."""
    skipped = ", ".join(f"`{m}`" for m in failed)
    note = f"\n> ⚡ **Proxy rotated:** {skipped} {'was' if len(failed)==1 else 'were'} unavailable — now using `{winner}`\n\n"
    import uuid, time as _time
    chunk = {
        "id": f"proxy-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "created": int(_time.time()),
        "model": VIRTUAL_MODEL,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": note}, "finish_reason": None}],
    }
    return f"data: {json.dumps(chunk)}\n\n".encode()


async def _blocking_failover(req: dict, hdrs: dict, models: list[dict]) -> Response:
    failed: list[str] = []
    for model in models:
        mid = model["id"]
        body = _or_body(mid, req)
        out_hdrs = {**_or_headers(hdrs), "content-length": str(len(body))}
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(f"{OPENROUTER_BASE}/chat/completions",
                                 headers=out_hdrs, content=body)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            log.warning("[ROTATE] %s: %s", mid, e)
            registry.mark_failed(mid)
            failed.append(mid)
            continue

        if r.status_code in FAILOVER_CODES:
            log.warning("[ROTATE] %s: HTTP %d", mid, r.status_code)
            registry.mark_failed(mid)
            failed.append(mid)
            continue

        try:
            data = r.json()
            if "error" in data and _is_overloaded_json(data):
                log.warning("[ROTATE] %s: overload in body", mid)
                registry.mark_failed(mid)
                failed.append(mid)
                continue
        except Exception:
            pass

        registry.mark_ok(mid)
        log.info("[OK] %s  HTTP %d", mid, r.status_code)
        resp_headers = {"X-Proxy-Model": mid}
        if failed:
            resp_headers["X-Proxy-Rotated"] = f"from={','.join(failed)} to={mid}"
        return Response(content=r.content, status_code=r.status_code,
                        media_type="application/json", headers=resp_headers)

    return JSONResponse(
        {"error": {"message": "All free programming models are currently unavailable", "code": 503}},
        status_code=503,
    )


async def _streaming_failover(
    req: dict, hdrs: dict, models: list[dict]
) -> AsyncGenerator[bytes, None]:
    failed: list[str] = []
    for model in models:
        mid = model["id"]
        body = _or_body(mid, req)
        out_hdrs = {**_or_headers(hdrs), "content-length": str(len(body))}

        try:
            async with httpx.AsyncClient(timeout=120) as c:
                async with c.stream(
                    "POST", f"{OPENROUTER_BASE}/chat/completions",
                    headers=out_hdrs, content=body,
                ) as r:
                    if r.status_code in FAILOVER_CODES:
                        log.warning("[ROTATE-S] %s: HTTP %d", mid, r.status_code)
                        registry.mark_failed(mid)
                        failed.append(mid)
                        continue

                    # Use a single iterator — calling aiter_bytes() twice raises StreamConsumed
                    stream_iter = r.aiter_bytes(4096)

                    # Buffer until we have enough to detect a JSON error vs real SSE
                    buf = b""
                    async for chunk in stream_iter:
                        buf += chunk
                        if len(buf) >= 512 or b"\n" in buf:
                            break

                    # A proper SSE response starts with "data:"
                    if buf and not buf.lstrip().startswith(b"data:"):
                        try:
                            data = json.loads(buf.decode(errors="replace").strip())
                            if "error" in data and _is_overloaded_json(data):
                                log.warning("[ROTATE-S] %s: overload in body", mid)
                                registry.mark_failed(mid)
                                failed.append(mid)
                                continue
                        except Exception:
                            pass

                    registry.mark_ok(mid)
                    log.info("[OK-S] %s", mid)

                    # Inject rotation notice as first content delta if we rotated
                    if failed:
                        yield _rotation_note_chunk(failed, mid)

                    yield buf
                    async for chunk in stream_iter:  # continue same iterator
                        yield chunk
                    return

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            log.warning("[ROTATE-S] %s: %s", mid, e)
            registry.mark_failed(mid)
            failed.append(mid)
            continue

    err = json.dumps({"error": {"message": "All free programming models unavailable", "code": 503}})
    yield f"data: {err}\n\ndata: [DONE]\n\n".encode()


async def _passthrough(req: dict, hdrs: dict) -> Response:
    body = json.dumps(req).encode()
    out_hdrs = {**_or_headers(hdrs), "content-length": str(len(body))}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{OPENROUTER_BASE}/chat/completions",
                         headers=out_hdrs, content=body)
    return Response(content=r.content, status_code=r.status_code,
                    media_type="application/json")


# Catch-all passthrough for any other OpenRouter endpoints
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all(request: Request, path: str):
    body = await request.body()
    hdrs = _or_headers(dict(request.headers))
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.request(
            method=request.method,
            url=f"{OPENROUTER_BASE}/{path}",
            headers=hdrs,
            content=body,
        )
    return Response(content=r.content, status_code=r.status_code,
                    headers=dict(r.headers))


# ---------------------------------------------------------------------------
# Standalone scanner (python3 openrouter_free_proxy.py --scan)
# ---------------------------------------------------------------------------

async def _run_scan(api_key: str) -> None:
    global OPENROUTER_API_KEY
    OPENROUTER_API_KEY = api_key
    print(f"Scanning OpenRouter for free programming models...")
    models = await _fetch_models()
    print(f"\nFound {len(models)} models:\n")
    for m in models:
        print(f"  {m['id']:<60}  ctx={m.get('context_length', '?')}")
    _save_cache(models)
    print(f"\nCached to {CACHE_FILE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global OPENROUTER_API_KEY

    parser = argparse.ArgumentParser(
        description="OpenRouter free programming models proxy with daily refresh and failover."
    )
    parser.add_argument("--api-key", default=os.environ.get("OPENROUTER_API_KEY", ""),
                        help="OpenRouter API key (or set OPENROUTER_API_KEY env var)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--scan", action="store_true",
                        help="Just scan and print free programming models, then exit")
    args = parser.parse_args()

    OPENROUTER_API_KEY = args.api_key
    if not OPENROUTER_API_KEY:
        print("ERROR: --api-key or OPENROUTER_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    if args.scan:
        asyncio.run(_run_scan(args.api_key))
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Starting OpenRouter free proxy on %s:%d", args.host, args.port)
    log.info("Virtual model name: %s", VIRTUAL_MODEL)
    log.info("Model cache: %s", CACHE_FILE)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
