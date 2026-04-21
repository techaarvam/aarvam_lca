# Local AI Agent Stack — Installation & Configuration

Full setup guide for running local Qwen models as coding agents on an RTX 5070
Blackwell (12 GB VRAM) machine running Ubuntu. Covers Ollama, the tool-call
proxy, qwencode, opencode, and OpenHands.

All scripts and proxy code in `~/qwenrundemo/aarvam_lca/` were written by Claude Code.

---

## Table of Contents

1. [Ollama](#1-ollama)
2. [Tool-Call Proxy](#2-tool-call-proxy)
3. [Models](#3-models)
4. [qwencode](#4-qwencode)
5. [opencode](#5-opencode)
6. [OpenHands](#6-openhands)
7. [Config File Reference](#7-config-file-reference)

---

## 1. Ollama

### Install

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

This installs the `ollama` binary to `/usr/local/bin/` and creates a systemd
service at `/etc/systemd/system/ollama.service`.

### Apply environment overrides

Create the override file:

```bash
sudo systemctl edit ollama
```

Paste the following, save, and close:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
```

This writes to `/etc/systemd/system/ollama.service.d/override.conf`.

| Variable | Value | Purpose |
|---|---|---|
| `OLLAMA_HOST` | `0.0.0.0:11434` | Listen on all interfaces (LAN access) |
| `OLLAMA_KEEP_ALIVE` | `-1` | Keep model loaded in VRAM indefinitely |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Evict previous model when loading a new one |
| `OLLAMA_NUM_PARALLEL` | `1` | One request at a time (single-user setup) |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | 8-bit KV cache — saves ~30% VRAM vs fp16 |

Apply and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
```

Verify:

```bash
systemctl status ollama
curl -s http://localhost:11434/api/tags | python3 -m json.tool | head -10
```

---

## 2. Tool-Call Proxy

A thin FastAPI proxy on port 8100 that sits between agent clients and Ollama.
It fixes two issues all Qwen models have with agent frameworks:

1. **Format rewriting** — Qwen2.5 returns tool calls as raw JSON/XML content;
   the proxy converts them to OpenAI `tool_calls` format.
2. **Required-field patching** — opencode's `bash` tool requires a `description`
   field that Qwen models never include; the proxy injects it.

### Install dependencies

```bash
pip install fastapi uvicorn httpx
```

### Start the proxy

```bash
cd ~/qwenrundemo/aarvam_lca && ./serve_tool_calls_proxy.sh
```

Or directly:

```bash
python3 ~/qwenrundemo/aarvam_lca/tool_calls_proxy.py --port 8100
```

Run it in a persistent terminal (tmux/screen) or create a systemd service.

### Verify

```bash
curl -sf http://127.0.0.1:8100/api/tags > /dev/null && echo "Proxy up"
```

> **Note:** The proxy and any vLLM server share port 8100 — run only one at a time.

---

## 3. Models

All models here are local Ollama registrations built from existing upstream
models with an explicit `num_ctx` override. On this setup, leaving `qwen3:8b`
without that override defaulted to a much smaller usable context window
(`4096`), while explicit `32768` and `65536` variants both worked in practice.

### qwen3-8b-64k (recommended on this machine)

```bash
ollama pull qwen3:8b   # 5.2 GB

cat > /tmp/Modelfile-qwen3-8b-64k << 'EOF'
FROM qwen3:8b
PARAMETER num_ctx 65536
EOF

ollama create qwen3-8b-64k -f /tmp/Modelfile-qwen3-8b-64k
```

This is the practical recommendation for this 12 GB Blackwell machine because
the 8B model leaves enough room to keep the layers on GPU while still pushing
to a much larger context than the default.

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
ollama pull qwen2.5-coder:7b-instruct-q4_K_M   # 4.7 GB

cat > /tmp/Modelfile-coder-7b-32k << 'EOF'
FROM qwen2.5-coder:7b-instruct-q4_K_M
PARAMETER num_ctx 32768
EOF

ollama create qwen2.5-coder-7b-32k -f /tmp/Modelfile-coder-7b-32k
```

Or run the setup script (does both pull and create):

```bash
cd ~/qwenrundemo/aarvam_lca && ./setup_qwen_ollama_models.sh
```

### Verify

```bash
ollama list | grep -E "qwen3-8b-64k|qwen3-8b-32k|coder-7b-32k"

curl -s http://localhost:11434/api/show -d '{"name":"qwen3-8b-64k"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('capabilities',[]))"
# Expected: ['completion', 'tools', 'thinking']
```

> **After a reboot:** Model registrations persist in
> `/usr/share/ollama/.ollama/models/`. Only the proxy needs to be restarted.

---

## 4. qwencode

### Install

```bash
# Requires Node.js (use nvm if needed)
npm install -g qwencode
```

Installed binary: `~/.nvm/versions/node/v22.21.0/bin/qwen` (via nvm).

### Configuration — `~/.qwen/settings.json`

Full file with all local models:

```json
{
  "security": {
    "auth": {
      "selectedType": "openai",
      "apiKey": "ollama",
      "baseUrl": "http://localhost:11434/v1"
    }
  },
  "modelProviders": {
    "openai": [
      {
        "id": "qwen3-8b-64k",
        "contextLength": 65536,
        "envKey": "OPENAI_API_KEY",
        "baseUrl": "http://127.0.0.1:8100/v1",
        "generationConfig": {
          "samplingParams": { "max_tokens": 4096 },
          "chatCompression": { "contextPercentageThreshold": 0.15 }
        }
      },
      {
        "id": "qwen3-8b-32k",
        "contextLength": 32768,
        "envKey": "OPENAI_API_KEY",
        "baseUrl": "http://127.0.0.1:8100/v1",
        "generationConfig": {
          "samplingParams": { "max_tokens": 4096 },
          "chatCompression": { "contextPercentageThreshold": 0.15 }
        }
      },
      {
        "id": "qwen3-8b-32k-direct",
        "contextLength": 32768,
        "envKey": "OPENAI_API_KEY",
        "baseUrl": "http://localhost:11434/v1",
        "generationConfig": {
          "samplingParams": { "max_tokens": 4096 },
          "chatCompression": { "contextPercentageThreshold": 0.15 }
        }
      },
      {
        "id": "qwen2.5-coder-7b-32k",
        "contextLength": 32768,
        "envKey": "OPENAI_API_KEY",
        "baseUrl": "http://127.0.0.1:8100/v1",
        "generationConfig": {
          "samplingParams": { "max_tokens": 4096 },
          "chatCompression": { "contextPercentageThreshold": 0.15 }
        }
      }
    ]
  },
  "model": {
    "name": "qwen3-8b-64k",
    "chatCompression": { "contextPercentageThreshold": 0.5 }
  },
  "$version": 3
}
```

`chatCompression.contextPercentageThreshold: 0.15` triggers context compression
when 15% of the window remains, for example around `9800` tokens at 64k,
preventing silent truncation.

### Usage

```bash
qwen -m qwen3-8b-64k           # recommended
qwen -m qwen3-8b-32k           # optional lower-context variant
qwen -m qwen2.5-coder-7b-32k -y
qwen                           # uses default model (qwen3-8b-64k)
```

`qwen3` generally does not require `-y` here because Ollama already exposes
native tool calls for it. The `qwen2.5-coder-7b-32k` fallback is the one that
benefits more from the proxy in agent-style flows.

---

## 5. opencode

### Install

```bash
curl -fsSL https://opencode.ai/install | bash
# Installs to ~/.opencode/bin/opencode
```

Or via npm:

```bash
npm install -g opencode-ai
```

### Configuration — `~/.config/opencode/opencode.json`

The key section to add for local models. The `ollama-proxy` provider routes
through the proxy (recommended); the `ollama` provider goes direct.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openrouter/qwen/qwen3-coder-next",
  "provider": {
    "ollama": {
      "name": "Ollama",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://127.0.0.1:11434/v1"
      },
      "models": {
        "qwen3-8b-64k": { "name": "qwen3-8b-64k", "tools": true },
        "qwen3-8b-32k": { "name": "qwen3-8b-32k", "tools": true },
        "qwen2.5-coder-7b-32k": { "name": "qwen2.5-coder-7b-32k", "tools": true }
      }
    },
    "ollama-proxy": {
      "name": "Ollama-Proxy",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://127.0.0.1:8100/v1"
      },
      "models": {
        "qwen3-8b-64k": { "name": "qwen3-8b-64k", "tools": true },
        "qwen3-8b-32k": { "name": "qwen3-8b-32k", "tools": true },
        "qwen2.5-coder-7b-32k": { "name": "qwen2.5-coder-7b-32k", "tools": true },
        "qwen2.5-coder-7b-q4": { "name": "qwen2.5-coder-7b-q4", "tools": true },
        "qwen2.5-coder-14b-q4": { "name": "qwen2.5-coder-14b-q4", "tools": true }
      }
    }
  }
}
```

> **Use `ollama-proxy` for agent tasks** — it patches the missing `description`
> field on bash tool calls that causes Qwen models to loop on retries.

### Usage

```bash
# Non-interactive (recommended for scripting)
~/.opencode/bin/opencode run \
  --model ollama-proxy/qwen3-8b-64k \
  --dangerously-skip-permissions \
  "your task here"

# Interactive TUI
~/.opencode/bin/opencode
# Type /models → select model → ollama-proxy/qwen3-8b-64k
```

`--dangerously-skip-permissions` auto-approves all tool calls. Omit to
approve each write/bash call manually.

---

## 6. OpenHands

### Install (Docker)

OpenHands runs as a Docker container. Images are pulled automatically on first run.

```bash
docker pull ghcr.io/openhands/openhands:0.59
```

The runtime sandbox image is pulled separately (large — ~12 GB):

```bash
docker pull ghcr.io/openhands/runtime:0.59-nikolaik
```

### Run script — `~/bin/openhands.sh`

```bash
#!/usr/bin/env bash
docker run -it --rm --pull=always \
  -e OH_PERSISTENCE_DIR=/.openhands-state \
  -e LOG_ALL_EVENTS=true \
  -e SANDBOX_VOLUMES=$HOME/openhands:/workspace:rw \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ~/.openhands-state:/.openhands-state \
  -p 3000:3000 \
  --add-host host.docker.internal:host-gateway \
  --name openhands-app \
  ghcr.io/openhands/openhands:0.59
```

Key options:

| Option | Purpose |
|---|---|
| `-e SANDBOX_VOLUMES=$HOME/openhands:/workspace:rw` | Mounts `~/openhands` as `/workspace` inside the agent sandbox — files the agent creates or edits appear here on the host |
| `-e OH_PERSISTENCE_DIR=/.openhands-state` | Persists conversation history and UI settings across container restarts |
| `-e LOG_ALL_EVENTS=true` | Verbose event logging — useful for debugging agent tool calls |
| `-v /var/run/docker.sock:/var/run/docker.sock` | Gives OpenHands access to Docker to spawn sandbox containers |
| `--add-host host.docker.internal:host-gateway` | Allows the container to reach Ollama on the host at `host.docker.internal:11434` |

> To change the workspace, replace `$HOME/openhands` with any directory.
> The agent sees it as `/workspace` regardless.

Make it executable:

```bash
chmod +x ~/bin/openhands.sh
```

### Start

```bash
~/bin/openhands.sh
# Then open http://localhost:3000 in a browser
```

To use a local Ollama model in OpenHands:
- In the UI settings, set provider to **OpenAI-compatible**
- Base URL: `http://host.docker.internal:11434/v1` (or `:8100` for proxy)
- API key: `ollama`
- Model: `qwen3-8b-64k`

### Workspace

Project files go in `~/openhands/` — this directory is mounted as `/workspace`
inside the container.

State (conversation history, settings) persists in `~/.openhands-state/`.

---

## 7. Config File Reference

| File | Purpose |
|---|---|
| `/etc/systemd/system/ollama.service.d/override.conf` | Ollama environment overrides |
| `~/.qwen/settings.json` | qwencode model list and default |
| `~/.config/opencode/opencode.json` | opencode providers and model list |
| `~/bin/openhands.sh` | OpenHands Docker run command |
| `~/qwenrundemo/aarvam_lca/tool_calls_proxy.py` | Proxy source (FastAPI) |
| `~/qwenrundemo/aarvam_lca/serve_tool_calls_proxy.sh` | Start proxy on port 8100 |
| `~/qwenrundemo/aarvam_lca/setup_qwen_ollama_models.sh` | Register the qwen2.5-coder-7b-32k fallback in Ollama |

### Startup order

```
1. systemctl start ollama          # (auto-starts on boot)
2. cd ~/qwenrundemo/aarvam_lca && ./serve_tool_calls_proxy.sh   # start proxy
3. qwen / opencode / openhands     # start agent client
```

---

## Model Quick Reference

| Model | Via | Context | Capabilities | Notes |
|---|---|---|---|---|
| `qwen3-8b-64k` | proxy `:8100` | 64k | tools, thinking | **Recommended on this 12 GB Blackwell setup** |
| `qwen3-8b-32k` | proxy `:8100` | 32k | tools, thinking | Lower-context option with the same base model |
| `qwen3-8b-32k-direct` | direct `:11434` | 32k | tools, thinking | Skip proxy when you do not need the bash-field patch |
| `qwen2.5-coder-7b-32k` | proxy `:8100` | 32k | tools | Fallback, and a possible fit for smaller mixed CPU+GPU setups |
| `qwen2.5-coder-14b-q4` | proxy `:8100` | 15k | tools | Higher quality, short sessions |
| `q3_32k.14:latest` | direct `:11434` | 32k | tools, thinking | Reasoning tasks |
