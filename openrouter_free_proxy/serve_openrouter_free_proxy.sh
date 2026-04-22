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

if [ -z "$OPENROUTER_API_KEY" ]; then
  echo "ERROR: OPENROUTER_API_KEY env var is not set." >&2
  echo "  export OPENROUTER_API_KEY=sk-or-v1-..." >&2
  exit 1
fi
API_KEY="$OPENROUTER_API_KEY"

exec python3 openrouter_free_proxy.py \
  --api-key "$API_KEY" \
  --port 8200 \
  "$@"
