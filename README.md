# aarvam_lca

Local Qwen tooling for two serving paths:

- `tool_calls_proxy.py`: Ollama proxy that rewrites Qwen tool-call output into OpenAI `tool_calls`
- `serve_qwen_toolcall.py`: vLLM launcher for the local Qwen GGUF models with the XML-to-tool-calls parser

Key docs:

- `README_local_qwen_setup.md`: Ollama proxy setup and agent-client usage
- `README_qwen_toolcall.md`: vLLM parser and launcher usage
- `INSTALL.md`: full local stack notes
