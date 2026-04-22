# OpenRouter Free Programming Models Proxy

Copyright (c) 2026 Tech Aarvam. Primary authors: Ram (Ramasubramanian B), Claude Code

A local OpenAI-compatible proxy that automatically discovers **currently available free programming models** on OpenRouter (subject to rate limits and potential changes), exposes them as a single virtual model name `current-free-model`, and rotates to the next available model when one is overloaded or down.

## ⚠️ Important Licensing & Usage Notes

- **Free access ≠ unlimited**: Free models on OpenRouter are subject to rate limits (typically 50 requests/day, 20 requests/minute) and may be provider-throttled during peak times
- **Model licenses vary**: Each model retains its original license from the provider (Apache 2.0, MIT, Llama Community License, NVIDIA Nemotron License, etc.) - check individual model pages for details
- **OpenRouter Terms Apply**: Your usage is governed by OpenRouter's Terms of Service; free access may change or be discontinued at any time
- **For commercial use**: Verify the specific upstream license for each model before using in products, redistribution, or fine-tuning
- **Data policies vary**: Providers may have different logging/data retention policies; use OpenRouter's data policy filtering if needed
- **License compliance**: Use `--include` and `--exclude` flags to filter models by ID to comply with specific licensing requirements or organizational policies

## How it works

- On startup, fetches all free programming models from OpenRouter (two-pass: category filter + pricing check).
- Can be refreshed manually (e.g., with `--scan`) or on startup; the cache may be updated up to every 24 hours as needed.
- Failing models (HTTP 429/502/503/504/529 or overload body) enter a **5-minute cooldown** before being retried.
- Models are sorted by parameter size, context length (largest first) so the best model is tried first.
- A cache file (`openrouter_free_models_cache.json`) is written alongside the script so the proxy can start offline and refresh later.

## Prerequisites

```bash
pip install fastapi uvicorn httpx
```

You also need an OpenRouter API key (free tier is sufficient): https://openrouter.ai/keys

## Quick start

```bash
# Set your API key once
export OPENROUTER_API_KEY=sk-or-v1-...

# Start the proxy (port 8200)
cd openrouter_free_proxy/
./serve_openrouter_free_proxy.sh
```

The proxy listens on `http://127.0.0.1:8200` and is compatible with any OpenAI-SDK client.

## Using with Claude Code / opencode

```bash
# Point Claude Code at the proxy
ANTHROPIC_BASE_URL=http://127.0.0.1:8200/v1 claude

# Or with opencode
opencode --model openrouter-free/current-free-model
```

## Manual invocation

```bash
# Specify port or host explicitly
python3 openrouter_free_proxy.py --api-key sk-or-v1-... --port 8200 --host 0.0.0.0

# Scan and print available free models, then exit (no server started)
./serve_openrouter_free_proxy.sh --scan
# or
python3 openrouter_free_proxy.py --api-key sk-or-v1-... --scan
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/status` | Current model, rotation state, cooldown list, next refresh time |
| `GET`  | `/v1/models` | All discovered free models + the `current-free-model` virtual entry |
| `POST` | `/v1/chat/completions` | Chat completions with automatic failover |
| `*`    | `/{path}` | Passthrough to OpenRouter for any other endpoint |

### Check status

```bash
curl http://127.0.0.1:8200/status | python3 -m json.tool
```

### Send a chat request using the virtual model

```bash
curl http://127.0.0.1:8200/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "current-free-model",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Use a specific model directly (passthrough, no failover)

```bash
curl http://127.0.0.1:8200/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google/gemma-4-26b-a4b-it:free",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Streaming

Pass `"stream": true` in the request body. On rotation, a one-line notice is prepended to the response indicating which model was substituted.

## Configuration (env vars / flags)

| Flag / Env var | Default | Description |
|----------------|---------|-------------|
| `--api-key` / `OPENROUTER_API_KEY` | *(required)* | OpenRouter API key |
| `--port` | `8200` | Listening port |
| `--host` | `127.0.0.1` | Listening host |
| `--scan` | — | Print free models and exit |
| `--include` | — | Comma-separated list of model IDs to include (if set, only these models are considered) |
| `--exclude` | — | Comma-separated list of model IDs to exclude (these models are never selected) |

Internal constants (edit `openrouter_free_proxy.py` to change):

| Constant | Default | Description |
|----------|---------|-------------|
| `REFRESH_HOURS` | `24` | How often to re-fetch the model list |
| `COOLDOWN_SECONDS` | `300` | How long a failing model is benched |
| `FAILOVER_CODES` | `429,502,503,504,529` | HTTP codes that trigger rotation |

## Files

```
openrouter_free_proxy/
├── openrouter_free_proxy.py          # Main proxy server
├── serve_openrouter_free_proxy.sh    # Convenience launcher (port 8200)
├── openrouter_free_models_cache.json # Auto-generated cache (gitignored if desired)
└── README.md                         # This file
```
