#!/usr/bin/env bash
# --------------------------------------------------
# Copyright
# --------------------------------------------------
#
# Tech Aarvam
# Copyright (c) 2026 Tech Aarvam.
# Primary authors: Ram (Ramasubramanian B), Claude Code
#
# Start the OpenRouter free programming models proxy on port 8200.
# Proxies "current-free-model" → best available free OpenRouter model.
# Refreshes model list from OpenRouter every 24 hours automatically.
# Rotates models on-the-fly when one is overloaded or unavailable.
#
# Run a one-off scan (no server):
#   ./serve_openrouter_free_proxy.sh --scan
set -e
cd "$(dirname "$0")"

API_KEY="${OPENROUTER_API_KEY:-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}"

exec python3 openrouter_free_proxy.py \
  --api-key "$API_KEY" \
  --port 8200 \
  "$@"
