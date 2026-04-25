# Local Qwen Agent Mode Setup

Full setup for running local Qwen models as large-context coding agents in
**opencode**, using Ollama as the inference backend and a thin proxy to patch
tool-call responses.

> All models listed here reuse existing Ollama models — none are newly
> developed here or pre-built downloadable "32k" or "64k" variants. We
> register local variants by taking a standard Ollama model and setting
> `num_ctx` explicitly, because leaving the default on this setup fell back to
> a much smaller usable context window.
> The proxy and all scripts in this repo were written by Claude Code.

---

## Recommended Model: `qwen3-8b-64k`

`qwen3:8b` is the practical recommendation on this machine because it balances
context length against full-GPU fit:
- Native tool calling through Ollama
- `thinking` capability
- 8B parameters, 5.2 GB — leaves room to keep the model fully on this 12 GB GPU
- In practice here, explicit `num_ctx 32768` and `num_ctx 65536` both worked, while leaving the base model at defaults fell back to `4096`
- Observed runtime snapshot on this setup:

```bash
((pyenv1)) ~/.qwen % ollama ps
NAME                   ID              SIZE      PROCESSOR    CONTEXT    UNTIL
qwen3-8b-64k:latest    1adc23451bf4    8.8 GB    100% GPU     40960      Forever
```

  This is a useful sanity check that the recommended model fits fully on the
  GPU in a practical coding-agent configuration, with a loaded context window
  of `40960` in that session.
- Compared with `qwen2.5-coder-7b-32k`, Qwen3 8B showed materially stronger coding quality in local testing

`qwen2.5-coder-7b-32k` is still kept as a fallback, especially for smaller
CPU+GPU hardware where an even smaller model may be the safer fit.

---

## Why the Proxy Exists

| Constraint | Detail |
|---|---|
| GPU | RTX 5070 Blackwell (sm_120a), 12 GB VRAM |
| vLLM | Only fp8 KV cache works on Blackwell — non-fp8 KV kernels fail with PTX error |
| vLLM + 7B | fp8 KV cache has a bug with Qwen2.5-7B's 7:1 GQA ratio — garbled output; 14B (5:1 GQA) unaffected |
| Ollama + Qwen2.5-7B | Returns tool calls as raw JSON/XML content, not OpenAI `tool_calls` |
| opencode bash tool | Requires a `description` field that Qwen models omit |
| Proxy fix | Rewrites bare-JSON/XML tool calls to proper format; injects missing required fields |

All models — including Qwen3 which has native tool calling — are routed
through the proxy so the `description` patch applies uniformly.

---

## Prerequisites

- Ollama installed and running (`systemctl start ollama` or `ollama serve`)
- Python 3.10+ with pip
- opencode installed at `~/.opencode/bin/opencode`

```bash
pip install fastapi uvicorn httpx
```

---

## Step 1 — Pull and Register Models

### qwen3-8b-64k (recommended)

```bash
ollama pull qwen3:8b   # 5.2 GB, one-time download

cat > /tmp/Modelfile-qwen3-8b-64k << 'EOF'
FROM qwen3:8b
PARAMETER num_ctx 65536
EOF

ollama create qwen3-8b-64k -f /tmp/Modelfile-qwen3-8b-64k
```

### qwen3-8b-32k (optional lower-context variant)

```bash
cat > /tmp/Modelfile-qwen3-8b-32k << 'EOF'
FROM qwen3:8b
PARAMETER num_ctx 32768
EOF

ollama create qwen3-8b-32k -f /tmp/Modelfile-qwen3-8b-32k
```

### qwen2.5-coder-7b-32k (fallback)

```bash
ollama pull qwen2.5-coder:7b-instruct-q4_K_M   # 4.7 GB, one-time download

cat > /tmp/Modelfile-coder-7b-32k << 'EOF'
FROM qwen2.5-coder:7b-instruct-q4_K_M
PARAMETER num_ctx 32768
EOF

ollama create qwen2.5-coder-7b-32k -f /tmp/Modelfile-coder-7b-32k
```

Or run `setup_qwen_ollama_models.sh` which does the qwen2.5 steps automatically:

```bash
cd ~/qwenrundemo/aarvam_lca && ./setup_qwen_ollama_models.sh
```

Verify capabilities:

```bash
curl -s http://localhost:11434/api/show -d '{"name":"qwen3-8b-64k"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('capabilities', []))"
# Expected: ['completion', 'tools', 'thinking']
```

> **After a reboot:** Ollama model registrations persist (stored in
> `/usr/share/ollama/.ollama/models/`). Just start the proxy — no re-registration needed.

---

## Step 2 — Start the Proxy

The proxy runs on port 8100, forwarding to Ollama at `localhost:11434`.
It intercepts `/v1/chat/completions` to:
- Convert bare-JSON/XML tool call content to proper OpenAI `tool_calls` format (Qwen2.5)
- Inject required fields the model omits — e.g. `description` for `bash`, `security_risk` for `execute_bash` (OpenHands)
- Normalize tool call argument keys to lowercase (handles case variations from different models)
- For reasoning models (Nemotron): collect `delta.reasoning` tokens and fall back to a non-streaming retry when the stream ends with reasoning-only and no tool call — avoids silent stalls

```bash
cd ~/qwenrundemo/aarvam_lca && ./serve_tool_calls_proxy.sh
```

Or directly:

```bash
python3 ~/qwenrundemo/aarvam_lca/tool_calls_proxy.py --port 8100
```

Leave this running in a terminal or tmux session.

**Verify:**

```bash
curl -sf http://127.0.0.1:8100/api/tags > /dev/null && echo "Proxy up"
```

---

## Step 3 — Use with opencode

Both models are registered in the `ollama-proxy` provider in
`~/.config/opencode/opencode.json`. No manual config needed.

**Run a task non-interactively:**

```bash
# Recommended
~/.opencode/bin/opencode run \
  --model ollama-proxy/qwen3-8b-64k \
  --dangerously-skip-permissions \
  "your task here"

# Optional 32k variant
~/.opencode/bin/opencode run \
  --model ollama-proxy/qwen3-8b-32k \
  --dangerously-skip-permissions \
  "your task here"

# Fallback
~/.opencode/bin/opencode run \
  --model ollama-proxy/qwen2.5-coder-7b-32k \
  --dangerously-skip-permissions \
  "your task here"
```

**Interactive TUI:**

```bash
~/.opencode/bin/opencode
# Type /models → select model → ollama-proxy/qwen3-8b-64k
```

> `--dangerously-skip-permissions` auto-approves all tool calls without prompting.
> Omit it to approve each step manually.

---

## Step 4 — Use with qwencode (optional)

Both models are registered in `~/.qwen/settings.json` pointing at the proxy.

```bash
qwen -m qwen3-8b-64k          # recommended
qwen -m qwen3-8b-32k          # optional lower-context variant
qwen -m qwen2.5-coder-7b-32k -y
```

`qwen3` generally does not need `-y` here because Ollama already exposes native
tool calls for it. The `qwen2.5-coder-7b-32k` fallback is the one that benefits
more from running through the proxy in agent-style flows.

---

## Tool Call Format Coverage

The proxy handles every tool call format observed from Qwen variants:

| Format | Source |
|---|---|
| Proper OpenAI `tool_calls` (native) | Qwen3 via Ollama |
| Bare JSON `{"name":..,"arguments":..}` | Qwen2.5-Coder via Ollama |
| JSON array `[{..},{..}]` | Multi-tool Qwen2.5 |
| `<tool_call>` XML | Qwen2.5 GGUF direct |
| `<response>` XML | Ollama q3 template |
| `<xml>` XML | Ollama-published 7B blob |

Plain text responses pass through unmodified.

### Required-field patching

The proxy injects fields that models omit but agent frameworks require:

| Tool | Injected field | Default value | Reason |
|---|---|---|---|
| `bash` | `description` | `"run command"` | opencode requires it |
| `execute_bash` | `security_risk` | `"low"` | OpenHands validates it; qwen3/nemotron omit it |

Argument keys are also lowercased — models sometimes emit `Security_Risk` or `Command` with wrong case.

To extend, edit `_REQUIRED_ARGS` near the top of `tool_calls_proxy.py`.

---

## Model Reference

| Model | Size | Context | Capabilities | Notes |
|---|---|---|---|---|
| `qwen3-8b-64k` | 5.2 GB | 64k | tools, thinking | **Recommended on this 12 GB Blackwell setup** |
| `qwen3-8b-32k` | 5.2 GB | 32k | tools, thinking | Lower-context option with the same base model |
| `qwen2.5-coder-7b-32k` | 4.7 GB | 32k | tools | Fallback for smaller CPU+GPU machines |
| `qwen2.5-coder-14b-q4` | 9 GB | 15k | tools | Higher quality per token, shorter practical context |
| `q3_32k.14:latest` | 9.3 GB | 32k | tools, thinking | Reasoning tasks |
| `nemotron-3-nano-64k` | ~3 GB | 64k | tools, reasoning | NVIDIA Nemotron 4B; fast, uses `delta.reasoning` stream |
| `nemotron-3-nano-128k` | ~3 GB | 128k | tools, reasoning | 128k context variant |
| `nemotron-3-nano-256k` | ~3 GB | 256k | tools, reasoning | Full 256k context variant |
| `nemotron-mini-64k` | ~3 GB | 64k | tools, reasoning | Nemotron-mini base, 64k |
| `nemotron-mini-128k` | ~3 GB | 128k | tools, reasoning | Nemotron-mini 128k variant |
| `nemotron-mini-256k` | ~3 GB | 256k | tools, reasoning | Nemotron-mini full 256k |

All models via the proxy on port 8100. The proxy and vLLM share port 8100 —
run only one at a time.

> **Nemotron streaming note:** Nemotron models output thinking in `delta.reasoning` chunks before
> emitting tool calls. The proxy handles this transparently — if the stream ends with reasoning only
> and no tool call, it retries non-streaming and re-emits the result as SSE.

---

Tech Aarvam  
Copyright (c) 2026 Tech Aarvam.  
Primary authors: Ram (Ramasubramanian B), Claude Code  
Additional support: Codex
