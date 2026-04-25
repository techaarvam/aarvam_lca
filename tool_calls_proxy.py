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
import sys
import time
import uuid

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

DEFAULT_UPSTREAM = "http://localhost:11434"
DEFAULT_PORT = 8100


# Non-argument fields the model sometimes adds alongside actual args
_META = {"description", "workdir", "timeout", "cwd"}


def _strip_reasoning_markup(text: str) -> str:
    """Remove reasoning markup that some models leak into visible content."""
    text = re.sub(r'<think\b[^>]*>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'</?think\b[^>]*>', '', text, flags=re.IGNORECASE)
    return text.strip()


def _json_object_candidates(text: str) -> list[str]:
    """
    Return balanced top-level JSON-ish object substrings.

    This is deliberately small and only tracks braces outside strings; it lets
    us find a tool object after leaked reasoning text or other preambles.
    """
    candidates: list[str] = []
    start = None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start:i + 1])
                start = None
    return candidates


def _loads_jsonish_dict(text: str) -> dict | None:
    """Parse common model JSON-ish variants into a dict."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        repaired = re.sub(r'([,{]\s*)([A-Za-z_][\w-]*)\s*:', r'\1"\2":', text)
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
        try:
            obj = json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            return None
    return obj if isinstance(obj, dict) else None


def _parse_jsonish_tool_call(text: str, fallback_tool_name: str | None = None,
                             tools: list[dict] | None = None) -> dict | None:
    """
    Parse malformed but recognizable tool-call text.

    Nemotron can emit a JSON-looking object with unquoted keys or with an
    over-long command string followed by JSON-ish metadata. Preserve the model's
    command text and let the client/tool layer execute or reject it normally.
    """
    obj = _loads_jsonish_dict(text)
    if obj is not None:
        return _parse_single_tool_call(json.dumps(obj), fallback_tool_name, tools)

    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', text, re.DOTALL)
    name = name_match.group(1) if name_match else fallback_tool_name
    if not name:
        return None

    args: dict = {}
    command_match = re.search(
        r'"command"\s*:\s*"(.*)"\s*,\s*"?(?:timeout|description|workdir|cwd|security_risk)"?\s*:',
        text,
        re.DOTALL,
    )
    if not command_match:
        command_match = re.search(r'"command"\s*:\s*"(.*)"\s*}', text, re.DOTALL)
    if command_match:
        args["command"] = command_match.group(1).replace('\\"', '"').strip()

    for key in ("timeout", "description", "workdir", "cwd", "security_risk"):
        m = re.search(rf'"?{key}"?\s*:\s*("([^"]*)"|[0-9]+|true|false|null)', text, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1)
        if raw.startswith('"') and raw.endswith('"'):
            args[key] = raw[1:-1]
        elif raw.isdigit():
            args[key] = int(raw)
        elif raw.lower() == "true":
            args[key] = True
        elif raw.lower() == "false":
            args[key] = False
        elif raw.lower() == "null":
            args[key] = None

    if args:
        return {"name": name, "arguments": args}
    return None


def _infer_tool_from_args(args: dict, tools: list[dict]) -> str | None:
    """
    Find the best-matching tool for an args-only dict by scoring parameter overlap.
    Returns the tool name if at least half the (non-meta) arg keys match a tool's params.
    """
    arg_keys = {k.lower() for k in args if k.lower() not in _META}
    if not arg_keys:
        return None
    best_name = None
    best_score = 0.0
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name", "")
        props = fn.get("parameters", {}).get("properties", {})
        param_keys = {k.lower() for k in props}
        if not param_keys:
            continue
        overlap = len(arg_keys & param_keys)
        score = overlap / len(arg_keys)
        if score > best_score:
            best_score = score
            best_name = name
    return best_name if best_score >= 0.5 else None


def _parse_single_tool_call(text: str, fallback_tool_name: str | None = None,
                             tools: list[dict] | None = None) -> dict | None:
    """Parse one JSON blob as a tool call, return {name, arguments} or None."""
    text = _strip_reasoning_markup(text.strip())
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if "name" in obj and ("arguments" in obj or "parameters" in obj):
        args = obj.get("arguments") or obj.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                pass
        return {"name": obj["name"], "arguments": args}
    # Model emitted arguments-only JSON (no "name" key).
    # Try explicit fallback first, then infer from the tools list by parameter matching.
    if "name" not in obj:
        candidate = fallback_tool_name or (_infer_tool_from_args(obj, tools) if tools else None)
        if candidate:
            args = {k: v for k, v in obj.items() if k.lower() not in _META}
            if args:
                return {"name": candidate, "arguments": args}
    return None


def _looks_like_tool_calls(text: str, fallback_tool_name: str | None = None,
                            tools: list[dict] | None = None) -> list[dict] | None:
    """
    Return list of tool call dicts if text contains one or more bare tool call
    JSON objects (possibly wrapped in XML tags or a JSON array). Returns None if not.
    """
    text = _strip_reasoning_markup(text.strip())
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
        candidate_results = []
        for candidate in _json_object_candidates(blob):
            tc = _parse_single_tool_call(candidate, fallback_tool_name, tools)
            if not tc:
                tc = _parse_jsonish_tool_call(candidate, fallback_tool_name, tools)
            if tc:
                candidate_results.append(tc)
        if candidate_results:
            results.extend(candidate_results)
            continue

        tc = _parse_single_tool_call(blob, fallback_tool_name, tools)
        if not tc:
            tc = _parse_jsonish_tool_call(blob, fallback_tool_name, tools)
        if tc:
            results.append(tc)

    if results:
        return results

    # Last resort: scan for any embedded JSON objects that look like tool calls.
    # Handles the case where the model wraps the JSON in explanatory text or a
    # markdown code fence mid-paragraph.
    for m in re.finditer(r'```(?:json|xml)?\s*(\{.*?\})\s*```', text, re.DOTALL):
        tc = _parse_single_tool_call(m.group(1), tools=tools)
        if tc:
            results.append(tc)
    if results:
        return results

    for candidate in _json_object_candidates(text):
        tc = _parse_single_tool_call(candidate, fallback_tool_name, tools)
        if not tc:
            tc = _parse_jsonish_tool_call(candidate, fallback_tool_name, tools)
        if tc:
            results.append(tc)
    if results:
        return results

    # Plain JSON objects anywhere in the text (no fences)
    for m in re.finditer(r'\{[^{}]*"name"\s*:[^{}]*"(?:arguments|parameters)"\s*:[^{}]*\{[^{}]*\}[^{}]*\}', text, re.DOTALL):
        tc = _parse_single_tool_call(m.group(0), tools=tools)
        if tc:
            results.append(tc)

    return results if results else None


_TOOLS_NOT_SUPPORTED_MSG = "does not support tools"


def _tools_to_system_prompt(tools: list[dict]) -> str:
    """Convert OpenAI-format tools list into a system-prompt tool description."""
    lines = [
        "You have access to tools. To call a tool, output ONLY a JSON object "
        '(no other text) with "name" and "arguments" keys. Example:\n'
        '{"name": "tool_name", "arguments": {"param": "value"}}\n\n'
        "Available tools:"
    ]
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name", "?")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])
        param_desc = ", ".join(
            f"{k}({'required' if k in required else 'optional'}): {v.get('description', v.get('type', ''))}"
            for k, v in props.items()
        )
        lines.append(f"- {name}: {desc}. Parameters: {param_desc}")
    return "\n".join(lines)


def _inject_tools_into_messages(req_json: dict) -> dict:
    """
    Strip the 'tools' field and inject tool descriptions into the system message.
    Returns a new request dict suitable for models that don't support native tools.
    """
    tools = req_json.get("tools", [])
    tool_system = _tools_to_system_prompt(tools)

    messages = list(req_json.get("messages", []))
    if messages and messages[0].get("role") == "system":
        messages[0] = {**messages[0], "content": messages[0]["content"] + "\n\n" + tool_system}
    else:
        messages = [{"role": "system", "content": tool_system}] + messages

    new_req = {k: v for k, v in req_json.items() if k != "tools"}
    new_req["messages"] = messages
    # Also strip tool_choice if present
    new_req.pop("tool_choice", None)
    return new_req


_REQUIRED_ARGS: dict[str, dict] = {
    "bash": {"description": "run command"},
    # OpenHands execute_bash requires security_risk; qwen3 omits it
    "execute_bash": {"security_risk": "low"},
}

_ARG_ALIASES: dict[str, dict[str, str]] = {
    # OpenCode's write tool requires camelCase.
    "write": {"filepath": "filePath"},
}

def _patch_args(name: str, args: dict) -> dict:
    """Inject any required fields that the model omitted for known tools."""
    aliases = _ARG_ALIASES.get(name, {})
    normalized = {aliases.get(k.lower(), k): v for k, v in args.items()}
    lower_keys = {k.lower() for k in normalized}
    required = _REQUIRED_ARGS.get(name, {})
    missing = {k: v for k, v in required.items() if k.lower() not in lower_keys}
    return {**missing, **normalized} if missing else normalized


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

    # Log every request
    print(f"[REQ] {request.method} /{path}", flush=True)
    if body and request.method == "POST":
        try:
            preview = json.loads(body)
            model = preview.get("model", "?")
            stream = preview.get("stream", False)
            msgs = len(preview.get("messages", []))
            tools = len(preview.get("tools", []))
            fns = len(preview.get("functions", []))
            print(f"      model={model} stream={stream} msgs={msgs} tools={tools} functions={fns}", flush=True)
            if tools == 0 and fns == 0 and msgs > 0:
                # Log last user message for context
                last = preview["messages"][-1]
                print(f"      last_msg role={last.get('role')} content={str(last.get('content',''))[:200]}", flush=True)
        except Exception:
            print(f"      body(raw)={body[:200]}", flush=True)

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

    # All named models have num_ctx baked into their Modelfile; do not override.
    # Re-encode body in case it was modified elsewhere.
    body = json.dumps(req_json).encode()
    headers["content-length"] = str(len(body))

    streaming = req_json.get("stream", False)
    has_tools = bool(req_json.get("tools"))
    # Single-tool name used as fallback when model emits args-only JSON
    _tool_list = req_json.get("tools") or []
    _sole_tool = _tool_list[0]["function"]["name"] if len(_tool_list) == 1 else None

    if not has_tools:
        # No tools — plain passthrough
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(url, headers=headers, content=body)
        if streaming:
            print(f"[RSP] no-tools streaming status={resp.status_code} len={len(resp.content)}", flush=True)
            # Log last few data lines
            for line in resp.content.decode(errors="replace").splitlines()[-5:]:
                if line.startswith("data:"):
                    print(f"      {line[:200]}", flush=True)
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

        # Retry with tools injected into system prompt if model rejects native tools
        if _TOOLS_NOT_SUPPORTED_MSG in str(data.get("error", {}).get("message", "")):
            print("[RTY] model rejected tools — retrying with system-prompt injection", flush=True)
            fallback_req = _inject_tools_into_messages(req_json)
            fallback_body = json.dumps(fallback_req).encode()
            fallback_headers = {**headers, "content-length": str(len(fallback_body))}
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(url, headers=fallback_headers, content=fallback_body)
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
            tc = _looks_like_tool_calls(msg["content"], _sole_tool, _tool_list)
            if tc:
                data = _build_tool_calls_response(data, tc)
            else:
                data = _patch_native_tool_calls(data)
        else:
            data = _patch_native_tool_calls(data)

        choice0 = data.get("choices", [{}])[0]
        finish = choice0.get("finish_reason", "?")
        usage = data.get("usage", {})
        print(f"[RSP] finish={finish} usage={usage}", flush=True)
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
        reasoning_parts = []
        is_tool_call_stream = False  # set if upstream returns proper tool_calls
        active_body = body
        active_headers = headers

        async def _collect_stream(stream_resp):
            nonlocal last_chunk, is_tool_call_stream
            raw_lines = []
            async for line in stream_resp.aiter_lines():
                raw_lines.append(line)
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
                if delta.get("reasoning"):
                    reasoning_parts.append(delta["reasoning"])
            return raw_lines

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", url, headers=active_headers, content=active_body) as resp:
                raw_lines = await _collect_stream(resp)

        # If no chunks but we got a non-data error line, check for "does not support tools"
        if not chunks:
            error_text = " ".join(raw_lines)
            if _TOOLS_NOT_SUPPORTED_MSG in error_text:
                print("[RTY] stream: model rejected tools — retrying with system-prompt injection", flush=True)
                fallback_req = _inject_tools_into_messages(req_json)
                fallback_body = json.dumps(fallback_req).encode()
                fallback_headers = {**active_headers, "content-length": str(len(fallback_body))}
                async with httpx.AsyncClient(timeout=300) as client:
                    async with client.stream("POST", url, headers=fallback_headers, content=fallback_body) as resp2:
                        await _collect_stream(resp2)

        full_content = "".join(content_parts)
        full_reasoning = "".join(reasoning_parts)
        finish = ((last_chunk or {}).get("choices") or [{}])[0].get("finish_reason", "stop")
        print(f"[STR] chunks={len(chunks)} is_tool_call_stream={is_tool_call_stream} "
              f"content_len={len(full_content)} reasoning_len={len(full_reasoning)} finish={finish}", flush=True)

        if is_tool_call_stream:
            # Already proper tool_calls stream — patch args then pass through
            for c in chunks:
                c = _patch_native_tool_calls(c) if c.get("choices") else c
                yield f"data: {json.dumps(c)}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Model emitted only reasoning with no tool call — fall back to non-streaming
        # which is more reliable for reasoning models (avoids finish_reason=stop quirk)
        if not full_content and full_reasoning and finish == "stop":
            print("[RTY] only reasoning, no tool call in stream — retrying non-streaming", flush=True)
            ns_req = {**req_json, "stream": False}
            ns_body = json.dumps(ns_req).encode()
            ns_headers = {**active_headers, "content-length": str(len(ns_body))}
            async with httpx.AsyncClient(timeout=300) as client:
                ns_resp = await client.post(url, headers=ns_headers, content=ns_body)
            try:
                ns_data = ns_resp.json()
            except Exception:
                ns_data = {}
            ns_choice = ns_data.get("choices", [{}])[0]
            ns_msg = ns_choice.get("message", {})
            if ns_msg.get("tool_calls"):
                # Non-streaming gave us a proper tool call — emit as SSE
                print(f"      non-stream retry got tool_calls: {[tc['function']['name'] for tc in ns_msg['tool_calls']]}", flush=True)
                ns_data = _patch_native_tool_calls(ns_data)
                fake_chunk = {
                    "id": last_chunk.get("id", "chatcmpl-retry") if last_chunk else "chatcmpl-retry",
                    "object": "chat.completion.chunk",
                    "created": last_chunk.get("created", int(time.time())) if last_chunk else int(time.time()),
                    "model": ns_data.get("model", req_json.get("model", "")),
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": None,
                                                        "tool_calls": ns_msg["tool_calls"]},
                                 "finish_reason": "tool_calls"}],
                }
                yield f"data: {json.dumps(fake_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                return
            elif ns_msg.get("content"):
                # Non-streaming gave plain text — emit as content delta
                full_content = ns_msg["content"]
                print(f"      non-stream retry gave content: {repr(full_content[:200])}", flush=True)

        # Check if full content is a tool call in text form
        if full_content:
            print(f"      content={repr(full_content[:500])}", flush=True)
        if finish == "stop" and full_content:
            tc = _looks_like_tool_calls(full_content, _sole_tool, _tool_list)
            if tc and last_chunk:
                print(f"      rewriting as tool_calls: {[t['name'] for t in tc]}", flush=True)
                yield _build_tool_calls_stream_chunk(last_chunk, tc)
                return

        # Not a tool call — pass through visible content chunks only.
        # Never surface raw reasoning as content: it would enter conversation history
        # and confuse the model on the next turn.
        visible = [c for c in chunks if (c.get("choices") or [{}])[0].get("delta", {}).get("content")]
        print(f"      passthrough {len(visible)}/{len(chunks)} visible chunks", flush=True)
        for c in visible:
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
