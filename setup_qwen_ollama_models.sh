#!/usr/bin/env bash
# One-shot setup/restore for the qwen2.5-coder-7b-32k Ollama fallback model.
# Safe to re-run at any time.
set -euo pipefail

MODELFILE=/tmp/Modelfile-coder-7b-32k
OLLAMA_BASE=qwen2.5-coder:7b-instruct-q4_K_M

echo "=== Step 1: Ollama base model ==="
if ollama list 2>/dev/null | grep -q "$OLLAMA_BASE"; then
    echo "  Already present: $OLLAMA_BASE"
else
    echo "  Pulling $OLLAMA_BASE (~4.7 GB, one-time download) ..."
    ollama pull "$OLLAMA_BASE"
fi

echo ""
echo "=== Step 2: Build Ollama model qwen2.5-coder-7b-32k ==="
cat > "$MODELFILE" << 'EOF'
FROM qwen2.5-coder:7b-instruct-q4_K_M
PARAMETER num_ctx 32768
EOF
echo "  Modelfile written: $MODELFILE"

ollama create qwen2.5-coder-7b-32k -f "$MODELFILE"
echo "  Model created: qwen2.5-coder-7b-32k"

echo ""
echo "=== Step 3: Verify capabilities ==="
caps=$(curl -s http://localhost:11434/api/show \
    -d '{"name":"qwen2.5-coder-7b-32k"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('capabilities',[]))")
echo "  Capabilities: $caps"
if echo "$caps" | grep -q "tools"; then
    echo "  OK — tool support detected"
else
    echo "  WARNING — 'tools' not in capabilities; proxy will still work"
fi

echo ""
echo "=== Done ==="
echo ""
echo "Start the proxy:"
echo "  cd $(dirname "$0") && ./serve_tool_calls_proxy.sh"
echo ""
echo "Use with opencode (qwen2.5 fallback):"
echo "  ~/.opencode/bin/opencode run --model ollama-proxy/qwen2.5-coder-7b-32k --dangerously-skip-permissions 'your task'"
echo ""
echo "Recommended on this 12 GB machine: use qwen3-8b-64k instead:"
echo "  ollama pull qwen3:8b"
echo "  printf 'FROM qwen3:8b\nPARAMETER num_ctx 65536\n' | ollama create qwen3-8b-64k -f /dev/stdin"
echo "  ~/.opencode/bin/opencode run --model ollama-proxy/qwen3-8b-64k --dangerously-skip-permissions 'your task'"
