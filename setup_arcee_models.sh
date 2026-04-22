#!/usr/bin/env bash
# --------------------------------------------------
# Copyright
# --------------------------------------------------
#
# Tech Aarvam
# Copyright (c) 2026 Tech Aarvam.
# Primary authors: Ram (Ramasubramanian B), Claude Code
#
# Download and register Arcee AI models with 64k/32k context for Ollama.
# Safe to re-run at any time.
set -euo pipefail

echo "=== Arcee AI Model Setup ==="
echo ""

# ── 1. Arcee-Agent (7B, Q4_K_M, 64k context) ────────────────────────────────
# Only Arcee model with native tool-calling (trained on Glaive FC v2 / Agent-FLAN)
HF_AGENT="hf.co/crusoeai/Arcee-Agent-GGUF:Q4_K_M"
AGENT_NAME="arcee-agent-64k"

echo "=== Arcee-Agent (7B Q4_K_M) ==="
if ollama list 2>/dev/null | grep -q "^hf.co/crusoeai/Arcee-Agent-GGUF"; then
    echo "  Base GGUF already present"
else
    echo "  Pulling $HF_AGENT (~4.7 GB)..."
    ollama pull "$HF_AGENT"
fi

cat > /tmp/Modelfile-arcee-agent-64k << 'EOF'
FROM hf.co/crusoeai/Arcee-Agent-GGUF:Q4_K_M
PARAMETER num_ctx 65536
EOF
ollama create "$AGENT_NAME" -f /tmp/Modelfile-arcee-agent-64k
echo "  Created: $AGENT_NAME (64k context)"

# ── 2. AFM-4.5B (4.5B, Q4_K_M, 64k context) ─────────────────────────────────
HF_AFM="hf.co/arcee-ai/AFM-4.5B-GGUF:Q4_K_M"
AFM_NAME="arcee-afm-64k"

echo ""
echo "=== Arcee AFM-4.5B (Q4_K_M) ==="
if ollama list 2>/dev/null | grep -q "^hf.co/arcee-ai/AFM-4.5B-GGUF"; then
    echo "  Base GGUF already present"
else
    echo "  Pulling $HF_AFM (~2.9 GB)..."
    ollama pull "$HF_AFM"
fi

cat > /tmp/Modelfile-arcee-afm-64k << 'EOF'
FROM hf.co/arcee-ai/AFM-4.5B-GGUF:Q4_K_M
PARAMETER num_ctx 65536
EOF
ollama create "$AFM_NAME" -f /tmp/Modelfile-arcee-afm-64k
echo "  Created: $AFM_NAME (64k context)"

# ── 3. SuperNova-Medius (14B, Q3_K_M, 32k context) ──────────────────────────
# 14B at Q3_K_M = 7.34GB + ~2.5GB KV for 32k = ~9.8GB — fits in 12GB VRAM
HF_SNM="hf.co/arcee-ai/SuperNova-Medius-GGUF:Q3_K_M"
SNM_NAME="arcee-supernova-32k"

echo ""
echo "=== Arcee SuperNova-Medius (14B Q3_K_M) ==="
if ollama list 2>/dev/null | grep -q "^hf.co/arcee-ai/SuperNova-Medius-GGUF"; then
    echo "  Base GGUF already present"
else
    echo "  Pulling $HF_SNM (~7.3 GB)..."
    ollama pull "$HF_SNM"
fi

cat > /tmp/Modelfile-arcee-supernova-32k << 'EOF'
FROM hf.co/arcee-ai/SuperNova-Medius-GGUF:Q3_K_M
PARAMETER num_ctx 32768
EOF
ollama create "$SNM_NAME" -f /tmp/Modelfile-arcee-supernova-32k
echo "  Created: $SNM_NAME (32k context)"

# ── 4. Verify capabilities ───────────────────────────────────────────────────
echo ""
echo "=== Verifying capabilities ==="
for MODEL in "$AGENT_NAME" "$AFM_NAME" "$SNM_NAME"; do
    caps=$(curl -s http://localhost:11434/api/show \
        -d "{\"name\":\"$MODEL\"}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('capabilities', []))" 2>/dev/null || echo "?")
    ctx=$(curl -s http://localhost:11434/api/show \
        -d "{\"name\":\"$MODEL\"}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('model_info',{}).get('llama.context_length','?'))" 2>/dev/null || echo "?")
    echo "  $MODEL  caps=$caps  ctx=$ctx"
done

echo ""
echo "=== Done ==="
echo ""
echo "Start Arcee proxy on port 8000:"
echo "  cd $(dirname "$0") && ./serve_arcee_proxy.sh"
echo ""
echo "Use with opencode:"
echo "  opencode --model arcee-proxy/arcee-agent-64k ..."
echo "  opencode --model arcee-proxy/arcee-afm-64k ..."
echo "  opencode --model arcee-proxy/arcee-supernova-32k ..."
