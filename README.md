# aarvam_lca

Local Qwen tooling for two serving paths:

- `tool_calls_proxy.py`: Ollama proxy that rewrites tool-call output into OpenAI `tool_calls` — supports Qwen, Nemotron, and other local models
- **Recommended model:** `qwen3-8b-64k` — native tool calling, better for verbose explanations, 100% accuracy, effective context ~40k on 12 GB VRAM ([benchmark](logs/benchmark_20260425_qwen3_vs_nemotron.md))
- `vllm/serve_qwen_toolcall.py`: vLLM launcher for the local Qwen GGUF models with the XML-to-tool-calls parser

The primary workflow in this repo is the Ollama proxy path. The vLLM adapter,
benchmark, and experiment notes are kept under `vllm/` as secondary material.

## Primary docs

- [local_agent_setup.md](local_agent_setup.md): Ollama proxy setup, model registrations, and agent-client usage
- [INSTALL.md](INSTALL.md): broader local stack notes for Ollama, qwencode, opencode, and OpenHands
- [PROJECT_REPORT.md](PROJECT_REPORT.md): project report for the Blackwell 5070 / 12 GB local coding-agent setup, findings matrix, and architecture diagrams

## vLLM

- [vllm/README.md](vllm/README.md): vLLM XML-to-tool-calls adapter notes and launcher usage
- [vllm/install_vllm.sh](vllm/install_vllm.sh): vLLM install helper for this Blackwell setup
- [vllm/vllm_benchmark.py](vllm/vllm_benchmark.py): benchmark script for the local Qwen GGUF runs

## License

MIT. See [LICENSE](LICENSE).

---

### Fascinating Proxy Context Behavior

**Observation:** OpenCode's proxy system automatically injects context-aware responses into the tool output, even when the script doesn't explicitly code for this behavior.

**Example:** When the model rotated from `qwen/qwen3-coder:free` to `arcee-ai/trinity-large-preview:free`, OpenCode automatically added a contextual message about the rotation, demonstrating intelligent context injection without explicit scripting.

**Implication:** This shows how OpenCode's proxy layer can enhance tooling with contextual awareness, creating emergent behaviors that improve user experience beyond the base script functionality.

---

Tech Aarvam  
Copyright (c) 2026 Tech Aarvam.  
Primary authors: Ram (Ramasubramanian B), Claude Code  
Additional support: Codex
