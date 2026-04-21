# Local Qwen Agent Mode Setup

Full setup for running small Qwen models as 32k-context coding agents in
**opencode**, using Ollama as the inference backend and a thin proxy to patch
tool-call responses.

> All models listed here are constructed locally — none are pre-built
> downloadable "32k" variants. We take a standard Ollama model and set
> `num_ctx 32768` to unlock the context window the weights already support.
> The proxy and all scripts in this repo were written by Claude Code.

---

## Recommended Model: `qwen3-8b-32k`

`qwen3:8b` is the best small model for agent mode on this machine:
- Native tool calling (proper OpenAI `tool_calls` format from Ollama)
- `thinking` capability
- 8B parameters, 5.2 GB — fits comfortably in 12 GB VRAM
- Reliably completes multi-step tasks (write file → run → capture output)

`qwen2.5-coder-7b-32k` is kept as a fallback but produces lower-quality
output and requires more proxy intervention to get tool calls working.

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

### qwen3-8b-32k (recommended)

```bash
ollama pull qwen3:8b   # 5.2 GB, one-time download

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
curl -s http://localhost:11434/api/show -d '{"name":"qwen3-8b-32k"}' \
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
- Inject required fields the model omits — e.g. `description` for the `bash` tool (all models)

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
# Press / → select model → ollama-proxy/qwen3-8b-32k
```

> `--dangerously-skip-permissions` auto-approves all tool calls without prompting.
> Omit it to approve each step manually.

---

## Step 4 — Use with qwencode (optional)

Both models are registered in `~/.qwen/settings.json` pointing at the proxy.

```bash
qwen -m qwen3-8b-32k -y       # YOLO (agent) mode, recommended
qwen -m qwen2.5-coder-7b-32k -y
```

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

| Tool | Injected field | Default value |
|---|---|---|
| `bash` | `description` | `"run command"` |

To extend, edit `_REQUIRED_ARGS` near the top of `tool_calls_proxy.py`.

---

## Model Reference

| Model | Size | Context | Capabilities | Quality |
|---|---|---|---|---|
| `qwen3-8b-32k` | 5.2 GB | 32k | tools, thinking | **Recommended** |
| `qwen2.5-coder-7b-32k` | 4.7 GB | 32k | tools | Fallback |
| `qwen2.5-coder-14b-q4` | 9 GB | 15k | tools | Higher quality, short sessions |
| `q3_32k.14:latest` | 9.3 GB | 32k | tools, thinking | Reasoning tasks |

All models via the proxy on port 8100. The proxy and vLLM share port 8100 —
run only one at a time.
