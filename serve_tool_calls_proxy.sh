#!/usr/bin/env bash
# Start the Ollama tool-call proxy on port 8100.
# Requires Ollama to be running with the desired local Qwen model registered.
set -e
cd "$(dirname "$0")"
exec python3 tool_calls_proxy.py --port 8100 "$@"
