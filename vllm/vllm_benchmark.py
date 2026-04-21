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
"""
vLLM benchmark: Qwen models at 16k/32k context, fp16 vs fp8 KV cache, GGUF q4_K_M weights.
GPU: RTX 5070 (sm_120 Blackwell, 12GB VRAM)

Blackwell note: awq_marlin kernel PTX missing for sm_120 in pre-built wheels.
Using GGUF load-format instead (bypasses Marlin/AWQ kernels, uses PyTorch ops).
32k/64k not achievable: vLLM pre-allocates full KV pool upfront (~3GB for 32k fp8 > available).
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from qwen_vllm_models import MODELS as SHARED_MODELS

# ---------------------------------------------------------------------------
# Model registry  (GGUF path — Blackwell sm_120 compatible)
# ---------------------------------------------------------------------------
# awq_marlin fails on Blackwell (sm_120 PTX missing in pre-built wheels).
# GGUF load-format works: uses PyTorch ops, no custom CUDA kernels needed.
# Symlinks point at existing Ollama blobs so no re-download required.
MODELS = [
    {
        "name": spec.name,
        "hf_id": spec.model,
        "tokenizer": spec.tokenizer,
        "quantization": spec.quantization,
        "dtype": spec.dtype,
        "load_format": spec.load_format,
    }
    for spec in SHARED_MODELS
]

# Memory reality (measured): model=8.58 GB, available KV=1.67 GB (after CUDA overhead).
# fp16 KV 16k needs 3.0 GB → does NOT fit (2×8×128×48 layers × fp16 × 16384 tokens).
# fp8  KV 16k needs 1.5 GB → fits, but vLLM fills all 1.67 GB then OOMs on sampler.
# Fix: --max-num-seqs 1 caps activation memory so fp8 16k can proceed.
# 32k of any dtype: does NOT fit (6+ GB needed).
CONTEXT_LENGTHS = [16384, 32768]   # 16k, 32k (64k won't fit: needs 3 GB fp8)

# fp16 baseline vs fp8 (≈ Ollama's KV_CACHE_TYPE=q8_0 compression)
KV_CACHE_DTYPES = ["auto", "fp8"]

VLLM_HOST = "127.0.0.1"
VLLM_PORT = 8100
GPU_UTIL = 0.95          # 0.95 * 11.48 GB = 10.91 GB; leaves ~1.64 GB for KV cache after 8.58 GB model
SERVER_STARTUP_TIMEOUT = 180  # seconds to wait for vLLM to load model
RESULTS_DIR = Path("results")

# ---------------------------------------------------------------------------
# Benchmark prompts (3 tiers: short / medium / long-context stress)
# ---------------------------------------------------------------------------
SHORT_PROMPT = """\
Write a complete Python script using numpy that:
1. Creates a 3x3 matrix
2. Computes its inverse
3. Verifies by multiplying original × inverse (should give identity)
4. Prints all three matrices

Output only the Python code, no explanation."""

MEDIUM_PROMPT = """\
Write a Python class `MatrixOps` that wraps numpy and provides these methods:
- `transpose(A)` — return transpose
- `matmul(A, B)` — return matrix product
- `inverse(A)` — return inverse, raise ValueError if singular
- `solve(A, b)` — solve Ax=b, return x
- `determinant(A)` — return scalar determinant

Include a `__repr__` and a short `demo()` classmethod that exercises all operations on a 3x3 example.
Output only the Python code."""

# Long prompt: large context filled with code, then a focused question.
def make_long_prompt(target_tokens: int) -> str:
    """Fill context with a realistic code base, then ask a question."""
    filler_module = '''\
import numpy as np
from typing import Optional, Tuple, List

class LinearAlgebra:
    """Comprehensive linear algebra toolkit built on NumPy."""

    def __init__(self, dtype=np.float64):
        self.dtype = dtype

    def lu_decompose(self, A: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (P, L, U) such that A = P @ L @ U."""
        from scipy.linalg import lu
        return lu(A)

    def qr_decompose(self, A: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        return np.linalg.qr(A)

    def svd(self, A: np.ndarray, full_matrices: bool = True):
        return np.linalg.svd(A, full_matrices=full_matrices)

    def cholesky(self, A: np.ndarray) -> np.ndarray:
        return np.linalg.cholesky(A)

    def eigendecompose(self, A: np.ndarray):
        return np.linalg.eig(A)

    def cond(self, A: np.ndarray) -> float:
        return float(np.linalg.cond(A))

    def rank(self, A: np.ndarray) -> int:
        return int(np.linalg.matrix_rank(A))

    def norm(self, A: np.ndarray, ord=None) -> float:
        return float(np.linalg.norm(A, ord=ord))

    def pinv(self, A: np.ndarray) -> np.ndarray:
        return np.linalg.pinv(A)

    def solve_lstsq(self, A: np.ndarray, b: np.ndarray):
        return np.linalg.lstsq(A, b, rcond=None)

    def is_positive_definite(self, A: np.ndarray) -> bool:
        try:
            np.linalg.cholesky(A)
            return True
        except np.linalg.LinAlgError:
            return False

    def gram_schmidt(self, A: np.ndarray) -> np.ndarray:
        """Orthonormalize columns of A via Gram-Schmidt."""
        Q = np.zeros_like(A, dtype=float)
        for i in range(A.shape[1]):
            v = A[:, i].astype(float)
            for j in range(i):
                v -= np.dot(Q[:, j], A[:, i]) * Q[:, j]
            norm = np.linalg.norm(v)
            Q[:, i] = v / norm if norm > 1e-10 else v
        return Q

    def power_iteration(self, A: np.ndarray, num_iter: int = 1000, tol: float = 1e-9):
        """Estimate dominant eigenvalue via power iteration."""
        n = A.shape[0]
        b = np.random.rand(n)
        eigenvalue = 0.0
        for _ in range(num_iter):
            b_new = A @ b
            b_new_norm = np.linalg.norm(b_new)
            b = b_new / b_new_norm
            new_eig = float(b @ A @ b)
            if abs(new_eig - eigenvalue) < tol:
                break
            eigenvalue = new_eig
        return eigenvalue, b

'''
    # Repeat filler to approximate target token count (rough: 1 token ≈ 4 chars)
    target_chars = target_tokens * 4
    repeated = filler_module
    while len(repeated) < target_chars - 1000:
        repeated += filler_module
    repeated = repeated[:target_chars]

    return f"""\
You are reviewing the following Python module:

```python
{repeated}
```

Task: Identify any numerical stability issues in the `gram_schmidt` method and rewrite it with a numerically stable modified Gram-Schmidt algorithm. Output only the corrected method."""


PROMPTS = {
    "short":  (SHORT_PROMPT,  80),   # (prompt_text, expected_output_tokens)
    "medium": (MEDIUM_PROMPT, 350),
}

# Long prompts are added per context-length in the runner (fill ~30% of context window)
LONG_FILL_FRACTION = 0.3


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class RunConfig:
    model_name: str
    hf_id: str
    tokenizer: str
    quantization: str
    dtype: str
    load_format: str
    ctx_len: int
    kv_dtype: str

@dataclass
class TaskResult:
    task: str
    prompt_tokens: int
    output_tokens: int
    ttft_ms: float           # time to first token
    total_ms: float
    tok_per_sec: float
    output_snippet: str
    passed: bool             # code ran without error
    error: str = ""

@dataclass
class ConfigResult:
    config: RunConfig
    gpu_mem_used_mb: float
    gpu_mem_total_mb: float
    tasks: list = field(default_factory=list)
    server_error: str = ""


# ---------------------------------------------------------------------------
# GPU memory helpers
# ---------------------------------------------------------------------------
def gpu_mem_mb() -> tuple[float, float]:
    """Return (used_MB, total_MB) for GPU 0."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            text=True
        ).strip().split(", ")
        return float(out[0]), float(out[1])
    except Exception:
        return 0.0, 0.0


# ---------------------------------------------------------------------------
# vLLM server lifecycle
# ---------------------------------------------------------------------------
def build_vllm_cmd(cfg: RunConfig) -> list[str]:
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", cfg.hf_id,
        "--host", VLLM_HOST,
        "--port", str(VLLM_PORT),
        "--max-model-len", str(cfg.ctx_len),
        "--kv-cache-dtype", cfg.kv_dtype,
        "--gpu-memory-utilization", str(GPU_UTIL),
        "--dtype", cfg.dtype,
        "--served-model-name", cfg.model_name,
        "--no-enable-log-requests",
        # Limit batch to 1 seq: reduces peak activation memory during dummy warmup run.
        # Without this, vLLM fills all available VRAM with KV pages then OOMs on sampler.
        "--max-num-seqs", "1",
        # Blackwell sm_120: enforce eager disables CUDA graph compilation
        "--enforce-eager",
    ]
    if cfg.tokenizer:
        cmd += ["--tokenizer", cfg.tokenizer]
    if cfg.quantization:
        cmd += ["--quantization", cfg.quantization]
    if cfg.load_format != "auto":
        cmd += ["--load-format", cfg.load_format]
    # Cap KV allocation to exactly ctx_len tokens for fp8.
    # Without this, vLLM fills ALL available VRAM with KV blocks (greedy), leaving
    # nothing for per-block metadata and init allocations → OOM during _initialize_kv_caches.
    # block_size=16 (default): ctx_len / 16 = exact number of blocks needed.
    if cfg.kv_dtype == "fp8":
        cmd += ["--num-gpu-blocks-override", str(cfg.ctx_len // 16)]
    return cmd


def wait_for_server(proc: subprocess.Popen, timeout: int = SERVER_STARTUP_TIMEOUT) -> bool:
    url = f"http://{VLLM_HOST}:{VLLM_PORT}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Bail early if the subprocess already died
        if proc.poll() is not None:
            return False
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def start_server(cfg: RunConfig) -> tuple[subprocess.Popen, str]:
    cmd = build_vllm_cmd(cfg)
    print(f"    CMD: {' '.join(cmd)}", flush=True)
    env = os.environ.copy()
    env["VLLM_USE_TRITON_FLASH_ATTN"] = "0"
    # Point FlashInfer JIT at nvcc 12.8 which supports compute_120a (Blackwell RTX 5070)
    env["PATH"] = "/usr/local/cuda-12.8/bin:" + env.get("PATH", "")
    # Reduce allocator fragmentation — recommended by PyTorch OOM message
    env["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
    RESULTS_DIR.mkdir(exist_ok=True)
    log_path = str(RESULTS_DIR / f"server_{cfg.model_name}_{cfg.ctx_len}_{cfg.kv_dtype}.log")
    log_fh = open(log_path, "w")
    proc = subprocess.Popen(
        cmd, stdout=log_fh, stderr=subprocess.STDOUT,
        env=env, preexec_fn=os.setsid
    )
    return proc, log_path


def stop_server(proc: subprocess.Popen):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=30)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    time.sleep(2)  # let GPU free memory


# ---------------------------------------------------------------------------
# Inference + metrics
# ---------------------------------------------------------------------------
def run_prompt(model_name: str, prompt: str, max_tokens: int = 500) -> TaskResult:
    url = f"http://{VLLM_HOST}:{VLLM_PORT}/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
    }

    start = time.perf_counter()
    first_token_t: Optional[float] = None
    output_text = ""
    prompt_tokens = 0
    output_tokens = 0

    try:
        with requests.post(url, json=payload, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                chunk = json.loads(data_str)
                delta = chunk["choices"][0]["delta"].get("content", "")
                if delta:
                    if first_token_t is None:
                        first_token_t = time.perf_counter()
                    output_text += delta
                # usage may appear in last chunk
                if chunk.get("usage"):
                    prompt_tokens = chunk["usage"].get("prompt_tokens", 0)
                    output_tokens = chunk["usage"].get("completion_tokens", 0)
    except Exception as e:
        total_ms = (time.perf_counter() - start) * 1000
        return TaskResult("", 0, 0, 0.0, total_ms, 0.0, "", False, str(e))

    total_s = time.perf_counter() - start
    ttft_ms = ((first_token_t - start) * 1000) if first_token_t else 0.0
    tok_per_sec = output_tokens / max(total_s - ttft_ms / 1000, 0.001)

    # Quick quality check: extract code block and try to compile it
    passed = check_code_quality(output_text)

    return TaskResult(
        task="",
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        ttft_ms=round(ttft_ms, 1),
        total_ms=round(total_s * 1000, 1),
        tok_per_sec=round(tok_per_sec, 1),
        output_snippet=output_text[:300].replace("\n", " "),
        passed=passed,
    )


def check_code_quality(text: str) -> bool:
    """Try to compile any Python code block found in the response."""
    import re
    code_blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    if not code_blocks:
        # No fenced block — try compiling the whole output
        code_blocks = [text]
    for code in code_blocks:
        try:
            compile(code, "<string>", "exec")
            return True
        except SyntaxError:
            pass
    return False


# ---------------------------------------------------------------------------
# Per-config benchmark run
# ---------------------------------------------------------------------------
def run_config(cfg: RunConfig) -> ConfigResult:
    label = f"{cfg.model_name} | ctx={cfg.ctx_len//1024}k | kv={cfg.kv_dtype}"
    print(f"\n{'='*70}", flush=True)
    print(f"  {label}", flush=True)
    print(f"{'='*70}", flush=True)

    result = ConfigResult(config=cfg, gpu_mem_used_mb=0.0, gpu_mem_total_mb=0.0)

    proc, log_path = start_server(cfg)
    print(f"  Server log: {log_path}", flush=True)
    print(f"  Waiting for server (up to {SERVER_STARTUP_TIMEOUT}s)...", flush=True)
    if not wait_for_server(proc):
        # Read last lines from log for diagnostics
        try:
            with open(log_path) as f:
                last_lines = f.readlines()[-10:]
            crash_info = "".join(last_lines).strip()
        except Exception:
            crash_info = "(no log)"
        stop_server(proc)
        result.server_error = f"Server failed to start. Last log:\n{crash_info}"
        print(f"  ERROR: server failed. See {log_path}", flush=True)
        print(f"  {crash_info[-300:]}", flush=True)
        return result

    mem_used, mem_total = gpu_mem_mb()
    result.gpu_mem_used_mb = mem_used
    result.gpu_mem_total_mb = mem_total
    print(f"  GPU mem after load: {mem_used:.0f} / {mem_total:.0f} MB ({100*mem_used/mem_total:.1f}%)", flush=True)

    # Build prompt set for this context length
    tasks = {**PROMPTS}
    fill_tokens = int(cfg.ctx_len * LONG_FILL_FRACTION)
    tasks["long"] = (make_long_prompt(fill_tokens), 200)

    for task_name, (prompt, max_tokens) in tasks.items():
        print(f"  Task [{task_name}] ...", end=" ", flush=True)
        r = run_prompt(cfg.model_name, prompt, max_tokens=max_tokens)
        r.task = task_name
        result.tasks.append(r)
        status = "PASS" if r.passed else "FAIL"
        if r.error:
            status = f"ERR: {r.error[:60]}"
        print(f"ttft={r.ttft_ms:.0f}ms  {r.tok_per_sec:.1f}tok/s  [{status}]", flush=True)

    stop_server(proc)
    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def render_markdown(all_results: list[ConfigResult]) -> str:
    lines = [
        "# vLLM Benchmark Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"GPU: RTX 5070 (sm_120 Blackwell, 12 GB VRAM)",
        "",
        "## Summary",
        "",
        "| Model | Ctx | KV dtype | GPU% | TTFT short(ms) | TTFT med(ms) | TTFT long(ms) | tok/s short | tok/s long | Pass |",
        "|-------|-----|----------|------|----------------|--------------|----------------|-------------|------------|------|",
    ]

    for r in all_results:
        cfg = r.config
        if r.server_error:
            lines.append(
                f"| {cfg.model_name} | {cfg.ctx_len//1024}k | {cfg.kv_dtype} "
                f"| OOM/ERR | — | — | — | — | — | — |"
            )
            continue

        gpu_pct = f"{100*r.gpu_mem_used_mb/r.gpu_mem_total_mb:.0f}%" if r.gpu_mem_total_mb else "?"
        by_task = {t.task: t for t in r.tasks}

        def cell(task: str, attr: str) -> str:
            t = by_task.get(task)
            return str(getattr(t, attr, "—")) if t else "—"

        def pass_cell() -> str:
            total = len(r.tasks)
            passed = sum(1 for t in r.tasks if t.passed)
            return f"{passed}/{total}"

        lines.append(
            f"| {cfg.model_name} | {cfg.ctx_len//1024}k | {cfg.kv_dtype} "
            f"| {gpu_pct} "
            f"| {cell('short','ttft_ms')} | {cell('medium','ttft_ms')} | {cell('long','ttft_ms')} "
            f"| {cell('short','tok_per_sec')} | {cell('long','tok_per_sec')} "
            f"| {pass_cell()} |"
        )

    lines += [
        "",
        "## Notes",
        "- **KV dtype `auto`**: fp16 (same as weights dtype) — baseline memory",
        "- **KV dtype `fp8`**: ~50% KV memory reduction, equivalent to Ollama `KV_CACHE_TYPE=q8_0`",
        "- **TTFT**: time to first token (ms) — lower is better",
        "- **tok/s**: decode throughput (output tokens/sec) — higher is better",
        "- **Pass**: tasks where model output compiled as valid Python",
        "- All models use AWQ 4-bit weights (≈ Ollama q4_K_M)",
        "- `--enforce-eager` mode used for Blackwell sm_120 compatibility",
        "",
        "## Ollama Baseline (from prior runs)",
        "| Model | Ctx | KV cache | Notes |",
        "|-------|-----|----------|-------|",
        "| qwen2.5-coder-14b q4_K_M | 16k | default | Worked well (opencode) |",
        "| qwen3-14b q4_K_M | 32k | q8_0 | Worked well at 87% VRAM (qwencode) |",
        "| qwen3-14b q4_K_M | 8k | any | Too small — degraded quality |",
        "",
        "## Raw Results",
        "```json",
    ]

    # Serialize results
    raw = []
    for r in all_results:
        d = asdict(r)
        raw.append(d)
    lines.append(json.dumps(raw, indent=2))
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    global GPU_UTIL
    parser = argparse.ArgumentParser(description="vLLM benchmark for Qwen models")
    parser.add_argument("--models", nargs="+",
                        help="Filter model names from registry (default: all)")
    parser.add_argument("--ctx", nargs="+", type=int,
                        help="Context lengths to test (default: 16384 32768 65536)")
    parser.add_argument("--kv", nargs="+", choices=["auto", "fp8"],
                        help="KV cache dtypes (default: auto fp8)")
    parser.add_argument("--gpu-util", type=float, default=GPU_UTIL,
                        help="vLLM GPU memory utilization (default 0.90)")
    args = parser.parse_args()
    GPU_UTIL = args.gpu_util

    models = [m for m in MODELS if not args.models or m["name"] in args.models]
    ctx_lengths = args.ctx or CONTEXT_LENGTHS
    kv_dtypes = args.kv or KV_CACHE_DTYPES

    if not models:
        print("No models matched. Check MODELS registry in script.")
        sys.exit(1)

    RESULTS_DIR.mkdir(exist_ok=True)

    all_results: list[ConfigResult] = []

    for model_cfg in models:
        for ctx in ctx_lengths:
            for kv in kv_dtypes:
                cfg = RunConfig(
                    model_name=model_cfg["name"],
                    hf_id=model_cfg["hf_id"],
                    tokenizer=model_cfg.get("tokenizer", ""),
                    quantization=model_cfg.get("quantization", ""),
                    dtype=model_cfg.get("dtype", "auto"),
                    load_format=model_cfg.get("load_format", "auto"),
                    ctx_len=ctx,
                    kv_dtype=kv,
                )
                result = run_config(cfg)
                all_results.append(result)

                # Save incremental JSON after each run
                raw_path = RESULTS_DIR / "raw_results.json"
                with open(raw_path, "w") as f:
                    json.dump([asdict(r) for r in all_results], f, indent=2)

    # Final report
    report_md = render_markdown(all_results)
    report_path = RESULTS_DIR / "report.md"
    report_path.write_text(report_md)

    print("\n" + "="*70)
    print("BENCHMARK COMPLETE")
    print(f"  Report: {report_path}")
    print(f"  Raw:    {RESULTS_DIR / 'raw_results.json'}")
    print("="*70)
    print()
    # Print table section directly
    for line in report_md.split("\n"):
        if line.startswith("|") or line.startswith("#") or line == "":
            print(line)
        if line.startswith("## Raw"):
            break


if __name__ == "__main__":
    main()
