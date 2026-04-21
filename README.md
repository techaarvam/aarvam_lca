Tech Aarvam  
Copyright (c) 2026 Tech Aarvam.  
Primary authors: Ram (Ramasubramanian B), Claude Code  
Additional support: Codex

# aarvam_lca

Local Qwen tooling for two serving paths:

- `tool_calls_proxy.py`: Ollama proxy that rewrites Qwen tool-call output into OpenAI `tool_calls`
- `vllm/serve_qwen_toolcall.py`: vLLM launcher for the local Qwen GGUF models with the XML-to-tool-calls parser

The primary workflow in this repo is the Ollama proxy path. The vLLM adapter,
benchmark, and experiment notes are kept under `vllm/` as secondary material.

## Primary docs

- [README_local_qwen_setup.md](README_local_qwen_setup.md): Ollama proxy setup, model registrations, and agent-client usage
- [INSTALL.md](INSTALL.md): broader local stack notes for Ollama, qwencode, opencode, and OpenHands
- [PROJECT_REPORT.md](PROJECT_REPORT.md): project report for the Blackwell 5070 / 12 GB local coding-agent setup, findings matrix, and architecture diagrams

## vLLM

- [vllm/README.md](vllm/README.md): vLLM XML-to-tool-calls adapter notes and launcher usage
- [vllm/install_vllm.sh](vllm/install_vllm.sh): vLLM install helper for this Blackwell setup
- [vllm/vllm_benchmark.py](vllm/vllm_benchmark.py): benchmark script for the local Qwen GGUF runs

## License

MIT. See [LICENSE](LICENSE).
