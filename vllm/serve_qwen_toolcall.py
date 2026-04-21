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
"""Start vLLM with a Qwen XML -> OpenAI tool_calls parser plugin."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from qwen_vllm_models import MODEL_INDEX, get_model_spec


DEFAULT_GPU_UTIL = "auto"
DEFAULT_GPU_HEADROOM_GB = 0.35
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8100
DEFAULT_MAX_MODEL_LEN = 15360
DEFAULT_KV_OFFLOAD_GB = 8.0
DEFAULT_CPU_OFFLOAD_GB = 8.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve local Qwen models behind vLLM with OpenAI tool_calls."
    )
    parser.add_argument(
        "--model",
        default="qwen2.5-coder-14b-q4",
        choices=sorted(MODEL_INDEX),
        help="Model alias from the local shared registry.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--max-model-len", type=int, default=DEFAULT_MAX_MODEL_LEN)
    parser.add_argument("--kv-cache-dtype", default="fp8", choices=["auto", "fp8"])
    parser.add_argument(
        "--kv-offloading-size",
        type=float,
        default=DEFAULT_KV_OFFLOAD_GB,
        help="KV offload buffer size in GiB. Set to 0 to disable KV offloading.",
    )
    parser.add_argument(
        "--kv-offloading-backend",
        default="native",
        choices=["native", "lmcache"],
        help="KV offload backend.",
    )
    parser.add_argument(
        "--gpu-memory-utilization",
        default=DEFAULT_GPU_UTIL,
        help="GPU utilization fraction, or 'auto' to size against current free VRAM.",
    )
    parser.add_argument(
        "--gpu-memory-headroom-gb",
        type=float,
        default=DEFAULT_GPU_HEADROOM_GB,
        help="Safety headroom in GiB reserved when auto-sizing GPU utilization.",
    )
    parser.add_argument("--max-num-seqs", type=int, default=1)
    parser.add_argument(
        "--cpu-offload-gb",
        type=float,
        default=DEFAULT_CPU_OFFLOAD_GB,
        help="CPU weight offload size in GiB. Set to 0 to disable weight offloading.",
    )
    parser.add_argument(
        "--offload-backend",
        default="uva",
        choices=["auto", "uva", "prefetch"],
        help="Model weight offload backend.",
    )
    parser.add_argument(
        "--disable-auto-tool-choice",
        action="store_true",
        help="Pass through tools but skip vLLM auto tool parsing.",
    )
    parser.add_argument(
        "--reasoning-parser",
        default=None,
        help="Override the reasoning parser. Default: use the model registry value.",
    )
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Extra raw arguments appended to the vLLM api_server invocation.",
    )
    parser.add_argument(
        "--print-cmd",
        action="store_true",
        help="Print the resolved vLLM command before exec.",
    )
    return parser


def query_gpu_memory_gib() -> tuple[float, float] | None:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        ).strip()
    except Exception:
        return None

    if not out:
        return None

    first = out.splitlines()[0]
    free_mb, total_mb = [float(part.strip()) for part in first.split(",", 1)]
    return free_mb / 1024.0, total_mb / 1024.0


def resolve_gpu_memory_utilization(requested: str, headroom_gb: float) -> float:
    try:
        requested_value = None if requested == "auto" else float(requested)
    except ValueError as exc:
        raise SystemExit(
            f"--gpu-memory-utilization must be a float or 'auto', got {requested!r}"
        ) from exc

    gpu_mem = query_gpu_memory_gib()
    if gpu_mem is None:
        return requested_value if requested_value is not None else 0.90

    free_gib, total_gib = gpu_mem
    safe_util = max(0.10, min(0.95, (free_gib - headroom_gb) / total_gib))

    if requested_value is None:
        print(
            f"Auto-selected --gpu-memory-utilization {safe_util:.3f} "
            f"from {free_gib:.2f}/{total_gib:.2f} GiB free "
            f"with {headroom_gb:.2f} GiB headroom.",
            file=sys.stderr,
            flush=True,
        )
        return safe_util

    if requested_value > safe_util:
        print(
            f"Capping --gpu-memory-utilization from {requested_value:.3f} "
            f"to {safe_util:.3f} because only {free_gib:.2f}/{total_gib:.2f} GiB "
            f"is free and {headroom_gb:.2f} GiB headroom is reserved.",
            file=sys.stderr,
            flush=True,
        )
        return safe_util

    return requested_value


def build_vllm_command(args: argparse.Namespace) -> list[str]:
    spec = get_model_spec(args.model)
    plugin_path = Path(__file__).with_name("qwen25_xml_tool_parser.py").resolve()
    gpu_memory_utilization = resolve_gpu_memory_utilization(
        args.gpu_memory_utilization,
        args.gpu_memory_headroom_gb,
    )

    cmd = [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        spec.model,
        "--tokenizer",
        spec.tokenizer,
        "--served-model-name",
        spec.name,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--max-model-len",
        str(args.max_model_len),
        "--dtype",
        spec.dtype,
        "--gpu-memory-utilization",
        f"{gpu_memory_utilization:.3f}",
        "--max-num-seqs",
        str(args.max_num_seqs),
        "--kv-cache-dtype",
        args.kv_cache_dtype,
        "--enforce-eager",
        "--no-enable-log-requests",
        "--tool-parser-plugin",
        str(plugin_path),
        "--tool-call-parser",
        "qwen25_xml",
    ]

    if args.kv_offloading_size > 0:
        cmd.extend(
            [
                "--kv-offloading-size",
                str(args.kv_offloading_size),
                "--kv-offloading-backend",
                args.kv_offloading_backend,
                "--disable-hybrid-kv-cache-manager",
            ]
        )
    if args.cpu_offload_gb > 0:
        cmd.extend(
            [
                "--offload-backend",
                args.offload_backend,
                "--cpu-offload-gb",
                str(args.cpu_offload_gb),
            ]
        )

    if spec.load_format and spec.load_format != "auto":
        cmd.extend(["--load-format", spec.load_format])
    if spec.quantization:
        cmd.extend(["--quantization", spec.quantization])
    if not args.disable_auto_tool_choice:
        cmd.append("--enable-auto-tool-choice")
    # num-gpu-blocks-override caps KV allocation to prevent OOM during warmup.
    # Only needed when NOT using KV offloading: with offloading active, vLLM
    # auto-sizes GPU KV to fit available VRAM and overflows the rest to CPU.
    if args.kv_cache_dtype == "fp8" and args.kv_offloading_size == 0:
        cmd.extend(["--num-gpu-blocks-override", str(args.max_model_len // 16)])

    reasoning_parser = (
        args.reasoning_parser
        if args.reasoning_parser is not None
        else spec.reasoning_parser
    )
    if reasoning_parser:
        cmd.extend(["--reasoning-parser", reasoning_parser])

    for extra_arg in args.extra_arg:
        cmd.append(extra_arg)

    return cmd


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["VLLM_USE_TRITON_FLASH_ATTN"] = "0"
    env["PATH"] = "/usr/local/cuda-12.8/bin:" + env.get("PATH", "")
    env["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
    return env


def main() -> int:
    args = build_parser().parse_args()
    cmd = build_vllm_command(args)
    if args.print_cmd:
        print(" ".join(cmd), flush=True)
        return 0
    os.execvpe(cmd[0], cmd, build_env())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
