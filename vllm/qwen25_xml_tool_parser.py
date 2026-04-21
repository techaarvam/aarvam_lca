#!/usr/bin/env python3
# --------------------------------------------------
# Copyright
# --------------------------------------------------
#
# Tech Aarvam
# Copyright (c) 2026 Tech Aarvam.
# Author: Claude Code
# Prompt engineer: Ram (Ramasubramanian B)
#
"""vLLM tool parser plugin for Qwen 2.5/3 JSON-in-XML tool calls."""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from vllm.entrypoints.chat_utils import make_tool_call_id
from vllm.entrypoints.openai.chat_completion.protocol import (
    ChatCompletionRequest,
)
from vllm.entrypoints.openai.engine.protocol import (
    DeltaFunctionCall,
    DeltaMessage,
    DeltaToolCall,
    ExtractedToolCallInformation,
    FunctionCall,
    ToolCall,
)
from vllm.logger import init_logger
from vllm.tokenizers import TokenizerLike
from vllm.tool_parsers.qwen3coder_tool_parser import Qwen3CoderToolParser
from vllm.tool_parsers import ToolParser, ToolParserManager
from vllm.tool_parsers.abstract_tool_parser import Tool

logger = init_logger(__name__)


@dataclass(frozen=True)
class ParsedToolCall:
    name: str
    arguments: str


@ToolParserManager.register_module(["qwen25_xml", "qwen_xml_json"])
class Qwen25XMLToolParser(ToolParser):
    """Translate Qwen chat-template tool XML into OpenAI tool_calls."""

    tool_call_start_token = "<tool_call>"
    tool_call_end_token = "</tool_call>"

    def __init__(self, tokenizer: TokenizerLike, tools: list[Tool] | None = None):
        super().__init__(tokenizer, tools)
        self._scan_pos = 0
        self._generated_tool_ids: list[str] = []
        self._stream_mode: str | None = None
        self._coder_parser = Qwen3CoderToolParser(tokenizer, tools)

    def adjust_request(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        # Qwen's tokenizer chat template already instructs the model to emit the
        # native XML wrapper. Adding structured-output constraints here tends to
        # fight that template instead of helping it.
        return request

    def extract_tool_calls(
        self,
        model_output: str,
        request: ChatCompletionRequest,
    ) -> ExtractedToolCallInformation:
        if self._looks_like_function_xml(model_output):
            result = self._coder_parser.extract_tool_calls(model_output, request)
            self.prev_tool_call_arr = list(self._coder_parser.prev_tool_call_arr)
            self.streamed_args_for_tool = list(self._coder_parser.streamed_args_for_tool)
            return result

        parsed_calls, content = self._parse_full_output(model_output)
        tool_calls = [
            ToolCall(
                id=make_tool_call_id(),
                type="function",
                function=FunctionCall(name=call.name, arguments=call.arguments),
            )
            for call in parsed_calls
        ]

        self.prev_tool_call_arr = [
            {"name": call.name, "arguments": call.arguments} for call in parsed_calls
        ]
        self.streamed_args_for_tool = [call.arguments for call in parsed_calls]

        return ExtractedToolCallInformation(
            tools_called=bool(tool_calls),
            tool_calls=tool_calls,
            content=content,
        )

    def extract_tool_calls_streaming(
        self,
        previous_text: str,
        current_text: str,
        delta_text: str,
        previous_token_ids: Sequence[int],
        current_token_ids: Sequence[int],
        delta_token_ids: Sequence[int],
        request: ChatCompletionRequest,
    ) -> DeltaMessage | None:
        if not previous_text or len(current_text) < self._scan_pos or (
            previous_text and not current_text.startswith(previous_text)
        ):
            self._reset_streaming_state()

        self._stream_mode = self._resolve_stream_mode(current_text)
        if self._stream_mode == "function":
            return self._extract_function_xml_streaming(current_text, delta_text, request)

        if not delta_text and delta_token_ids and self.prev_tool_call_arr:
            return DeltaMessage(content="")

        content_parts: list[str] = []
        delta_tool_calls: list[DeltaToolCall] = []
        pos = self._scan_pos

        while True:
            start = current_text.find(self.tool_call_start_token, pos)
            if start == -1:
                safe_end = self._safe_content_end(current_text, pos)
                if safe_end > pos:
                    content_parts.append(current_text[pos:safe_end])
                    pos = safe_end
                break

            if start > pos:
                content_parts.append(current_text[pos:start])
                pos = start

            end = current_text.find(self.tool_call_end_token, start)
            if end == -1:
                break

            raw_block = current_text[start + len(self.tool_call_start_token) : end]
            parsed = self._parse_tool_call_block(raw_block)
            if parsed is None:
                content_parts.append(
                    current_text[start : end + len(self.tool_call_end_token)]
                )
                pos = end + len(self.tool_call_end_token)
                continue

            tool_index = len(self.prev_tool_call_arr)
            tool_id = self._ensure_tool_id(tool_index, parsed.name)
            delta_tool_calls.append(
                DeltaToolCall(
                    index=tool_index,
                    id=tool_id,
                    type="function",
                    function=DeltaFunctionCall(
                        name=parsed.name,
                        arguments=parsed.arguments,
                    ),
                )
            )
            self.prev_tool_call_arr.append(
                {"name": parsed.name, "arguments": parsed.arguments}
            )
            self.streamed_args_for_tool.append(parsed.arguments)
            pos = end + len(self.tool_call_end_token)

        self._scan_pos = pos

        if not content_parts and not delta_tool_calls:
            return None

        content = "".join(content_parts) or None
        if delta_tool_calls and content is not None:
            return DeltaMessage(content=content, tool_calls=delta_tool_calls)
        if delta_tool_calls:
            return DeltaMessage(tool_calls=delta_tool_calls)
        return DeltaMessage(content=content)

    def _reset_streaming_state(self) -> None:
        self._scan_pos = 0
        self.prev_tool_call_arr = []
        self.streamed_args_for_tool = []
        self._generated_tool_ids = []
        self._stream_mode = None
        self._coder_parser._reset_streaming_state()
        self._coder_parser.prev_tool_call_arr = []
        self._coder_parser.streamed_args_for_tool = []

    def _ensure_tool_id(self, index: int, name: str) -> str:
        while len(self._generated_tool_ids) <= index:
            self._generated_tool_ids.append(make_tool_call_id(func_name=name))
        return self._generated_tool_ids[index]

    def _parse_full_output(
        self, model_output: str
    ) -> tuple[list[ParsedToolCall], str | None]:
        parsed_calls: list[ParsedToolCall] = []
        content_parts: list[str] = []
        pos = 0

        while True:
            start = model_output.find(self.tool_call_start_token, pos)
            if start == -1:
                content_parts.append(model_output[pos:])
                break

            content_parts.append(model_output[pos:start])
            end = model_output.find(self.tool_call_end_token, start)
            if end == -1:
                content_parts.append(model_output[start:])
                break

            raw_block = model_output[start + len(self.tool_call_start_token) : end]
            parsed = self._parse_tool_call_block(raw_block)
            if parsed is None:
                content_parts.append(
                    model_output[start : end + len(self.tool_call_end_token)]
                )
            else:
                parsed_calls.append(parsed)
            pos = end + len(self.tool_call_end_token)

        content = self._normalize_content("".join(content_parts))
        return parsed_calls, content

    def _parse_tool_call_block(self, raw_block: str) -> ParsedToolCall | None:
        payload = self._load_jsonish(raw_block)
        if not isinstance(payload, dict):
            return None

        name = payload.get("name")
        arguments = payload.get("arguments", {})
        if not isinstance(name, str) or not name:
            return None

        arguments_json = self._normalize_arguments(arguments)
        if arguments_json is None:
            return None

        return ParsedToolCall(name=name, arguments=arguments_json)

    def _load_jsonish(self, text: str) -> Any:
        stripped = text.strip()
        candidates = [stripped]

        if stripped.startswith("```"):
            fenced = stripped.split("\n", 1)
            if len(fenced) == 2:
                tail = fenced[1]
                if tail.endswith("```"):
                    candidates.append(tail[:-3].strip())

        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            candidates.append(stripped[first_brace : last_brace + 1])

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                try:
                    return ast.literal_eval(candidate)
                except (ValueError, SyntaxError):
                    continue
        logger.debug("Failed to parse tool payload: %r", stripped)
        return None

    def _normalize_arguments(self, arguments: Any) -> str | None:
        if isinstance(arguments, str):
            stripped = arguments.strip()
            if not stripped:
                return "{}"
            parsed = self._load_jsonish(stripped)
            if parsed is None:
                return stripped
            return json.dumps(parsed, ensure_ascii=False)
        return json.dumps(arguments, ensure_ascii=False)

    def _normalize_content(self, content: str) -> str | None:
        normalized = content.strip()
        return normalized or None

    def _looks_like_function_xml(self, text: str) -> bool:
        return "<function=" in text and "</function>" in text

    def _resolve_stream_mode(self, text: str) -> str | None:
        if self._stream_mode is not None:
            return self._stream_mode
        if "<function=" in text:
            return "function"
        if self.tool_call_start_token in text:
            return "json"
        return None

    def _safe_content_end(self, text: str, start: int) -> int:
        tail = text[start:]
        hold_back = 0
        for marker in (self.tool_call_start_token, "<function="):
            max_check = min(len(marker) - 1, len(tail))
            for size in range(1, max_check + 1):
                if marker.startswith(tail[-size:]):
                    hold_back = max(hold_back, size)
        if hold_back:
            return len(text) - hold_back
        return len(text)

    def _extract_function_xml_streaming(
        self,
        current_text: str,
        delta_text: str,
        request: ChatCompletionRequest,
    ) -> DeltaMessage | None:
        if not delta_text and self.prev_tool_call_arr:
            return DeltaMessage(content="")

        content_parts: list[str] = []
        delta_tool_calls: list[DeltaToolCall] = []
        pos = self._scan_pos

        while True:
            start = current_text.find("<function=", pos)
            if start == -1:
                safe_end = self._safe_function_content_end(current_text, pos)
                if safe_end > pos:
                    content_parts.append(current_text[pos:safe_end])
                    pos = safe_end
                break

            if start > pos:
                content_parts.append(current_text[pos:start])
                pos = start

            end = current_text.find("</function>", start)
            if end == -1:
                break

            block = current_text[start : end + len("</function>")]
            parsed = self._parse_function_xml_block(block, request)
            if parsed is None:
                content_parts.append(block)
                pos = end + len("</function>")
                continue

            tool_index = len(self.prev_tool_call_arr)
            tool_id = self._ensure_tool_id(tool_index, parsed.name)
            delta_tool_calls.append(
                DeltaToolCall(
                    index=tool_index,
                    id=tool_id,
                    type="function",
                    function=DeltaFunctionCall(
                        name=parsed.name,
                        arguments=parsed.arguments,
                    ),
                )
            )
            self.prev_tool_call_arr.append(
                {"name": parsed.name, "arguments": parsed.arguments}
            )
            self.streamed_args_for_tool.append(parsed.arguments)
            pos = end + len("</function>")

        self._scan_pos = pos

        if not content_parts and not delta_tool_calls:
            return None

        content = "".join(content_parts) or None
        if delta_tool_calls and content is not None:
            return DeltaMessage(content=content, tool_calls=delta_tool_calls)
        if delta_tool_calls:
            return DeltaMessage(tool_calls=delta_tool_calls)
        return DeltaMessage(content=content)

    def _parse_function_xml_block(
        self, block: str, request: ChatCompletionRequest
    ) -> ParsedToolCall | None:
        result = self._coder_parser.extract_tool_calls(block, request)
        if not result.tool_calls:
            return None
        tool_call = result.tool_calls[0]
        if not tool_call.function or not tool_call.function.name:
            return None
        return ParsedToolCall(
            name=tool_call.function.name,
            arguments=tool_call.function.arguments,
        )

    def _safe_function_content_end(self, text: str, start: int) -> int:
        tail = text[start:]
        hold_back = 0
        marker = "<function="
        max_check = min(len(marker) - 1, len(tail))
        for size in range(1, max_check + 1):
            if marker.startswith(tail[-size:]):
                hold_back = size
        if hold_back:
            return len(text) - hold_back
        return len(text)
