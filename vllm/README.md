# vLLM Qwen XML Tool Adapter

This repo now includes a vLLM tool parser plugin that converts Qwen 2.5/3
chat-template tool output like:

```xml
<tool_call>
{"name":"read_file","arguments":{"path":"demo/solve.py"}}
</tool_call>
```

into OpenAI-style `tool_calls` on the vLLM API surface.

It reuses the same local model artifacts already used by the benchmark:

- `qwen2.5-coder-14b-q4` -> `/tmp/qwen25-coder-14b-q4.gguf`
- `qwen3-14b-q4` -> `/tmp/qwen3-14b-q4.gguf`

## Files

- `qwen25_xml_tool_parser.py`: vLLM parser plugin
- `serve_qwen_toolcall.py`: launcher for the local models
- `qwen_vllm_models.py`: shared model registry used by both the launcher and the benchmark

## Start vLLM

```bash
python3 vllm/serve_qwen_toolcall.py --model qwen2.5-coder-14b-q4 --max-model-len 15360 --port 8100
```

For Qwen 3:

```bash
python3 vllm/serve_qwen_toolcall.py --model qwen3-14b-q4 --max-model-len 15360 --port 8100
```

The launcher automatically adds:

- `--enable-auto-tool-choice`
- `--kv-cache-dtype fp8`
- `--kv-offloading-size 8.0 --kv-offloading-backend native --disable-hybrid-kv-cache-manager`
- `--offload-backend uva --cpu-offload-gb 8.0`
- `--tool-parser-plugin /path/to/qwen25_xml_tool_parser.py`
- `--tool-call-parser qwen25_xml`
- `--reasoning-parser qwen3` for the Qwen 3 registry entry

The launcher now defaults `--gpu-memory-utilization` to `auto`. It queries
current free VRAM with `nvidia-smi`, subtracts `0.35 GiB` of headroom, and
caps the final utilization accordingly before launching vLLM.

The default `--max-model-len` is `15360`. On this RTX 5070 / 12 GB setup,
that is the highest context length vLLM reported as fitting once the model was
fully loaded with fp8 KV cache.

Pass `--kv-offloading-size 0` or `--cpu-offload-gb 0` to disable either offload mode.
You can still force a specific target with `--gpu-memory-utilization 0.88`, but
the launcher will cap it downward if the current free-memory snapshot cannot
support that request safely.

## Client Request

Point any OpenAI-compatible client at the local vLLM server and send normal
tool definitions:

```bash
curl http://127.0.0.1:8100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-coder-14b-q4",
    "messages": [
      {"role": "user", "content": "Read demo/solve.py and tell me what it does."}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "read_file",
          "description": "Read a local file",
          "parameters": {
            "type": "object",
            "properties": {
              "path": {"type": "string"}
            },
            "required": ["path"]
          }
        }
      }
    ],
    "tool_choice": "auto"
  }'
```

If the model emits Qwen XML, vLLM responses will expose standard OpenAI
`tool_calls` instead of raw `<tool_call>...</tool_call>` text.

---

Tech Aarvam  
Copyright (c) 2026 Tech Aarvam.  
Author: Claude Code  
Prompt engineer: Ram (Ramasubramanian B)
