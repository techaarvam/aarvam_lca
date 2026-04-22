#!/usr/bin/env bash
# --------------------------------------------------
# Copyright
# --------------------------------------------------
#
# Tech Aarvam
# Copyright (c) 2026 Tech Aarvam.
# Primary authors: Ram (Ramasubramanian B), Claude Code
#
# Start the Ollama tool-call proxy on port 8000 for Arcee models.
# Requires Ollama to be running with Arcee models registered.
set -e
cd "$(dirname "$0")"
# Logs available at /tmp/proxy-8000.log when run with nohup or redirect
exec python3 tool_calls_proxy.py --port 8000 "$@"
