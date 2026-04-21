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
"""Shared model registry for the local Qwen vLLM experiments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    model: str
    tokenizer: str
    quantization: str = ""
    dtype: str = "float16"
    load_format: str = "gguf"
    reasoning_parser: str = ""


MODELS: list[ModelSpec] = [
    ModelSpec(
        name="qwen2.5-coder-7b-q4",
        model="/tmp/qwen25-coder-7b-q4.gguf",
        tokenizer="Qwen/Qwen2.5-Coder-7B-Instruct",
    ),
    ModelSpec(
        name="qwen2.5-coder-7b-awq",
        model="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        tokenizer="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        quantization="awq",
        load_format="auto",
    ),
    ModelSpec(
        name="qwen2.5-coder-14b-q4",
        model="/tmp/qwen25-coder-14b-q4.gguf",
        tokenizer="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
    ),
    ModelSpec(
        name="qwen3-14b-q4",
        model="/tmp/qwen3-14b-q4.gguf",
        tokenizer="Qwen/Qwen3-14B",
        reasoning_parser="qwen3",
    ),
]


MODEL_INDEX = {spec.name: spec for spec in MODELS}


def get_model_spec(name: str) -> ModelSpec:
    try:
        return MODEL_INDEX[name]
    except KeyError as exc:
        available = ", ".join(sorted(MODEL_INDEX))
        raise KeyError(f"Unknown model {name!r}. Available: {available}") from exc
