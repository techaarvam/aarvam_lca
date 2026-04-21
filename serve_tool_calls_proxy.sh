#!/usr/bin/env bash
# --------------------------------------------------
# Copyright
# --------------------------------------------------
#
# Tech Aarvam
# Copyright (c) 2026 Tech Aarvam.
# Primary authors: Ram (Ramasubramanian B), Claude Code
# Additional support: Codex
#
# Start the Ollama tool-call proxy on port 8100.
# Requires Ollama to be running with the desired local Qwen model registered.
set -e
cd "$(dirname "$0")"
exec python3 tool_calls_proxy.py --port 8100 "$@"
