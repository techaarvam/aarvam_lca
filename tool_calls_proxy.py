#!/usr/bin/env python3
# --------------------------------------------------
# Copyright
# --------------------------------------------------
#
# Tech Aarvam
# Copyright (c) 2026 Tech Aarvam.
# Primary authors: Ram (Ramasubramanian B), Claude Code
# Additional support: Codex
#
"""
Proxy for Ollama models that emit tool calls as raw JSON content.

Wraps the Ollama OpenAI-compatible API on a local port. When a response has
finish_reason=stop but the content is a bare tool-call JSON object
({"name": ..., "arguments": ...}), it converts that into a proper OpenAI
tool_calls response so qwencode agent mode works correctly.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

DEFAULT_UPSTREAM = "http://localhost:11434"
DEFAULT_PORT = 8100


def _parse_single_tool_call(text: str) -> dict | None:
    """Parse one JSON blob as a tool call, return {name, arguments} or None."""
    text = text.strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(obj, dict) and "name" in obj and (
        "arguments" in obj or "parameters" in obj
    ):
        args = obj.get("arguments") or obj.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                pass
        return {"name": obj["name"], "arguments": args}
    return None


def _looks_like_tool_calls(text: str) -> list[dict] | None:
    """
    Return list of tool call dicts if text contains one or more bare tool call
    JSON objects (possibly wrapped in XML tags or a JSON array). Returns None if not.
    """
    text = text.strip()
    # Strip markdown code fences
    text = re.sub(r'^```(?:json|xml)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # Try a JSON array of tool calls first
    if text.startswith('['):
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                results = []
                for item in arr:
                    if isinstance(item, dict) and "name" in item and (
                        "arguments" in item or "parameters" in item
                    ):
                        args = item.get("arguments") or item.get("parameters") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        results.append({"name": item["name"], "arguments": args})
                if results:
                    return results
        except (json.JSONDecodeError, ValueError):
            pass

    # Collect JSON blobs — XML-wrapped or blank-line-separated
    blobs: list[str] = []
    for tag in ('tool_call', 'response', 'xml'):
        matches = re.findall(rf'<{tag}[^>]*>\s*(.*?)\s*</{tag}>', text, re.DOTALL)
        if matches:
            blobs = matches
            break

    if not blobs:
        blobs = [b.strip() for b in re.split(r'\n\s*\n', text) if b.strip()]

    if not blobs:
        blobs = [text]

    results = []
    for blob in blobs:
        tc = _parse_single_tool_call(blob)
        if tc:
            results.append(tc)

    if results:
        return results

    # Last resort: scan for any embedded JSON objects that look like tool calls.
    # Handles the case where the model wraps the JSON in explanatory text or a
    # markdown code fence mid-paragraph.
    for m in re.finditer(r'```(?:json|xml)?\s*(\{.*?\})\s*```', text, re.DOTALL):
        tc = _parse_single_tool_call(m.group(1))
        if tc:
            results.append(tc)
    if results:
        return results

    # Plain JSON objects anywhere in the text (no fences)
    for m in re.finditer(r'\{[^{}]*"name"\s*:[^{}]*"(?:arguments|parameters)"\s*:[^{}]*\{[^{}]*\}[^{}]*\}', text, re.DOTALL):
        tc = _parse_single_tool_call(m.group(0))
        if tc:
            results.append(tc)

    return results if results else None


_REQUIRED_ARGS: dict[str, dict] = {
    "bash": {"description": "run command"},
}

def _patch_args(name: str, args: dict) -> dict:
    """Inject any required fields that the model omitted for known tools."""
    required = _REQUIRED_ARGS.get(name, {})
    missing = {k: v for k, v in required.items() if k not in args}
    return {**missing, **args} if missing else args


def _patch_native_tool_calls(data: dict) -> dict:
    """Patch tool call arguments in a native (non-rewritten) response."""
    choices = data.get("choices", [])
    patched = False
    new_choices = []
    for choice in choices:
        msg = choice.get("message", {})
        tcs = msg.get("tool_calls")
        if tcs:
            new_tcs = []
            for tc in tcs:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}
                patched_args = _patch_args(name, args)
                if patched_args is not args:
                    patched = True
                    tc = {**tc, "function": {**fn, "arguments": json.dumps(patched_args)}}
                new_tcs.append(tc)
            choice = {**choice, "message": {**msg, "tool_calls": new_tcs}}
        new_choices.append(choice)
    return {**data, "choices": new_choices} if patched else data


def _build_tool_calls_response(original: dict, tool_calls: list[dict]) -> dict:
    choice = original["choices"][0]
    tc_list = [
        {
            "id": "call_" + uuid.uuid4().hex[:12],
            "type": "function",
            "function": {
                "name": tc["name"],
                "arguments": json.dumps(_patch_args(tc["name"], tc["arguments"])),
            },
        }
        for tc in tool_calls
    ]
    return {
        **original,
        "choices": [
            {
                **choice,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tc_list,
                },
            }
        ],
    }


def _build_tool_calls_stream_chunk(original_chunk: dict, tool_calls: list[dict]) -> str:
    """Build a complete streaming response: tool_calls deltas then [DONE]."""
    chunk_id = original_chunk.get("id", "chatcmpl-" + uuid.uuid4().hex[:8])
    created = original_chunk.get("created", int(time.time()))
    model = original_chunk.get("model", "unknown")

    role_chunk = {
        "id": chunk_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": None},
                     "finish_reason": None}],
    }
    tc_deltas = [
        {
            "index": i,
            "id": "call_" + uuid.uuid4().hex[:12],
            "type": "function",
            "function": {
                "name": tc["name"],
                "arguments": json.dumps(_patch_args(tc["name"], tc["arguments"])),
            },
        }
        for i, tc in enumerate(tool_calls)
    ]
    tc_chunk = {
        "id": chunk_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {"tool_calls": tc_deltas},
                     "finish_reason": None}],
    }
    finish_chunk = {
        "id": chunk_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
    }
    return (
        f"data: {json.dumps(role_chunk)}\n\n"
        f"data: {json.dumps(tc_chunk)}\n\n"
        f"data: {json.dumps(finish_chunk)}\n\n"
        "data: [DONE]\n\n"
    )


app = FastAPI()
_upstream: str = DEFAULT_UPSTREAM


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(request: Request, path: str):
    url = f"{_upstream}/{path}"
    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)

    # Only intercept chat completions
    if path != "v1/chat/completions" or request.method != "POST":
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )
        return Response(content=resp.content, status_code=resp.status_code,
                        headers=dict(resp.headers))

    try:
        req_json = json.loads(body)
    except Exception:
        req_json = {}

    streaming = req_json.get("stream", False)
    has_tools = bool(req_json.get("tools"))

    if not has_tools:
        # No tools — plain passthrough
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(url, headers=headers, content=body)
        if streaming:
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type="text/event-stream")
        return Response(content=resp.content, status_code=resp.status_code,
                        headers=dict(resp.headers))

    if not streaming:
        # Non-streaming with tools: collect response and maybe rewrite
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(url, headers=headers, content=body)
        try:
            data = resp.json()
        except Exception:
            return Response(content=resp.content, status_code=resp.status_code)

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        if (
            choice.get("finish_reason") == "stop"
            and not msg.get("tool_calls")
            and msg.get("content")
        ):
            tc = _looks_like_tool_calls(msg["content"])
            if tc:
                data = _build_tool_calls_response(data, tc)
            else:
                data = _patch_native_tool_calls(data)
        else:
            data = _patch_native_tool_calls(data)

        return Response(
            content=json.dumps(data),
            status_code=resp.status_code,
            media_type="application/json",
        )

    # Streaming with tools: collect all chunks, check if content is tool call
    async def stream_with_fix():
        chunks = []
        last_chunk = None
        content_parts = []
        is_tool_call_stream = False  # set if upstream returns proper tool_calls

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", url, headers=headers, content=body) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except Exception:
                        continue
                    chunks.append(chunk)
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    last_chunk = chunk
                    delta = choices[0].get("delta", {})
                    if delta.get("tool_calls"):
                        is_tool_call_stream = True
                    if delta.get("content"):
                        content_parts.append(delta["content"])

        if is_tool_call_stream:
            # Already proper tool_calls stream — patch args then pass through
            for c in chunks:
                c = _patch_native_tool_calls(c) if c.get("choices") else c
                yield f"data: {json.dumps(c)}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Check if full content is a tool call
        full_content = "".join(content_parts)
        finish = (last_chunk or {}).get("choices", [{}])[0].get("finish_reason", "stop")
        if finish == "stop" and full_content:
            tc = _looks_like_tool_calls(full_content)
            if tc and last_chunk:
                yield _build_tool_calls_stream_chunk(last_chunk, tc)
                return

        # Not a tool call — pass through original chunks
        for c in chunks:
            yield f"data: {json.dumps(c)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_with_fix(), media_type="text/event-stream")


def main():
    global _upstream
    parser = argparse.ArgumentParser(
        description="Proxy Ollama OpenAI API with tool call JSON → tool_calls fix."
    )
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM,
                        help="Upstream Ollama base URL")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    _upstream = args.upstream
    print(f"Starting proxy on {args.host}:{args.port} → {_upstream}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
