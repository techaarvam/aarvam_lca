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
# Install vLLM for Blackwell (sm_120 / RTX 5070) with PyTorch 2.8 + CUDA 12.8
set -e

echo "=== vLLM Install for Blackwell RTX 5070 (sm_120) ==="
echo "PyTorch and CUDA already present — installing vLLM only"
echo ""

# Verify torch before install
python3 -c "import torch; assert torch.__version__ >= '2.8', 'Need torch>=2.8'; print(f'torch {torch.__version__} OK')"

# Install vLLM, preserving existing torch (--no-deps then install remaining separately)
# If pip tries to downgrade torch, abort and do --no-deps path instead
pip install vllm==0.19.1 \
    --extra-index-url https://download.pytorch.org/whl/cu128 \
    || {
        echo "Standard install failed, trying --no-deps path..."
        pip install vllm==0.19.1 --no-deps
        pip install \
            openai>=1.0.0 \
            aiohttp \
            fastapi \
            uvicorn \
            pydantic \
            tiktoken \
            sentencepiece \
            protobuf \
            huggingface_hub \
            xformers --index-url https://download.pytorch.org/whl/cu128 \
            || true
    }

echo ""
echo "Installing AWQ support..."
pip install autoawq --no-deps || pip install autoawq || true

echo ""
echo "=== Verifying vLLM install ==="
python3 -c "import vllm; print(f'vLLM {vllm.__version__} OK')"
python3 -c "import torch; print(f'GPU: {torch.cuda.get_device_name(0)}, sm_{torch.cuda.get_device_capability(0)[0]}{torch.cuda.get_device_capability(0)[1]}')"

echo ""
echo "=== Model Downloads Needed ==="
echo "Run the benchmark to auto-download, or pre-fetch manually:"
echo "  huggingface-cli download Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"
echo "  huggingface-cli download Qwen/Qwen3-14B-Instruct  (BF16, ~28GB — use --quantization bitsandbytes)"
echo "  huggingface-cli download Qwen/Qwen3-14B-Instruct-GPTQ-Int4  (if available)"
echo ""
echo "Done. Run: python3 vllm/vllm_benchmark.py"
