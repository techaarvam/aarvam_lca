# Model Benchmark: qwen3-8b-64k vs nemotron-3-nano-128k

**Date:** 2026-04-25  
**Machine:** RTX 5070 Blackwell, 12 GB VRAM  
**Proxy:** tool_calls_proxy.py on port 8100 → Ollama 11434  
**qwen3 thinking:** disabled (`options.think=false`) for fair speed comparison  

---

## Current Nemotron Tool-Call Status

This benchmark was run with controlled prompts that did not hit the later
OpenCode tool-call compatibility issue. Its speed, factual-answer, and context
results are still useful for those prompt types, but they should not be read as
proof that Nemotron is equally reliable for full coding-agent workflows.

A later OpenCode run using
`nemotron-nano-9b-v2-q3_k_m-128k:latest` and the prompt:

> generate 5 numpy demos in /tmp/numpy_demos2 directory for transpose, matrix multiply, inverse, solve, concatenate. Run them and store the outputs in output_<name>.txt

exposed two separate problems:

- **Proxy compatibility:** Nemotron emitted tool calls as leaked reasoning
  markup plus adjacent JSON or JSON-like objects, sometimes with unquoted keys
  such as `timeout: 240000`. `tool_calls_proxy.py` has since been updated to
  strip leaked think markup, split adjacent JSON tool objects, tolerate the
  observed JSON-ish shape, and preserve OpenCode's `filePath` argument casing.
- **Model command quality:** after the proxy converted responses into valid
  OpenAI `tool_calls`, OpenCode was able to invoke `write` and `bash`, but the
  model still generated bad Python and shell commands in follow-up steps. That
  is a model behavior issue, not only a response-shape issue.

Practical takeaway: Qwen 3 remains the recommended daily driver for OpenCode
tool workflows. Nemotron remains interesting for speed and long context, but it
is experimental for multi-step agent tool use until more stress cases pass.

---

## Standard Prompts

| Test | qwen3-8b-64k | nemotron-3-nano-128k | Winner |
|---|---|---|---|
| Math (primes <50, answer=328) | 30.1s, 2847 tok, 94.5 tok/s ✓ | 4.0s, 305 tok, 76.4 tok/s ✓ | Nemotron (7.5× faster) |
| Code (palindrome + tests) | 10.6s, 1071 tok, 100.8 tok/s | 3.6s, 567 tok, 159.2 tok/s | Nemotron (3× faster) |
| Reasoning (sheep riddle, answer=9) | 9.5s, 962 tok, 100.9 tok/s ✓ | 0.9s, 122 tok, 143.1 tok/s ✓ | Nemotron (10× faster) |
| TCP/UDP (3 bullet points) | 6.1s, 615 tok, 100.8 tok/s | 2.3s, 354 tok, 157.0 tok/s | Nemotron (2.6× faster) |
| Creative (haiku) | 6.5s, 651 tok, 100.9 tok/s | 5.5s, 882 tok, 161.4 tok/s | Tie (quality similar) |
| **TOTAL** | **101.8s, 6824 tok, 67.1 tok/s** | **29.8s, 2592 tok, 87.1 tok/s** | **Nemotron 3.4× faster** |

**Quality:** Both models answered every standard benchmark question correctly. qwen3 tends to be more verbose and elaborate; nemotron is concise and accurate on these prompts. These results do not cover multi-step OpenCode tool execution.

---

## Needle-in-Haystack Context Tests

A unique codename was hidden at the 90% position of a generated document. Both models were asked to retrieve it.

| Context size | Prompt tokens | qwen3-8b-64k | nemotron-3-nano-128k |
|---|---|---|---|
| ~5k tokens | ~2,680 | 2.8s ✓ FOUND | 1.0s ✓ FOUND |
| ~35k tokens | ~18,430 | 9.7s ✓ FOUND | 5.5s ✓ FOUND |
| ~80k tokens | qwen3: truncated to **40,960** / nemotron: **42,069** | 26.5s ✓ FOUND* | 7.2s ✓ FOUND |

*qwen3 at 80k: Ollama capped the prompt at exactly 40,960 tokens (the model's loaded context limit). The needle survived truncation here because it fell within the retained window — this cannot be relied on for arbitrary document lengths or needle positions.

### Key context finding

- **qwen3-8b-64k** is registered with `num_ctx 65536` but Ollama loads it at **40,960** on this 12 GB GPU due to VRAM constraints alongside system overhead.
- **nemotron-3-nano-128k** genuinely processes **131,072** tokens. The 256k variant (`nemotron-3-nano-256k`) extends this further to **262,144** tokens with no weight change — only the KV cache grows.
- At 80k context, nemotron answered **3.7× faster** (7.2s vs 26.5s).

---

## Summary

| Metric | qwen3-8b-64k | nemotron-3-nano-128k |
|---|---|---|
| Parameters | 8.2B | 4B |
| VRAM loaded | ~7.9 GB | ~7.1 GB |
| Effective context (this GPU) | ~40k tokens | 128k tokens (256k variant available) |
| Avg tok/s (standard prompts) | 99.6 | 159.4 |
| Total benchmark time | 101.8s | 29.8s |
| Factual accuracy on these prompts | 100% | 100% |
| Response style | Verbose, elaborated | Concise, direct |
| Tool calling | Native (Ollama) | Via proxy reasoning-fallback |

### Recommendation

**For this 12 GB Blackwell setup, `qwen3-8b-64k` is the recommended daily driver:**

- Native tool calling without proxy reasoning-fallback path
- Better for verbose, elaborated explanations (documentation, tutorials)
- Correct answers on all benchmark prompts in this log
- Strong reasoning capabilities with thinking tokens support
- Effective context of ~40k tokens on this GPU (limited by VRAM overhead)

qwen3-8b-64k is preferred when response verbosity and elaboration are desired. nemotron-3-nano-128k remains useful for:
- **3.4× faster** end-to-end across all task types
- **3× more effective context** (128k vs ~40k actual) — critical for real codebases
- Identical answer accuracy on the controlled benchmark prompts
- Smaller VRAM footprint leaves more headroom for the KV cache at large contexts
- The tool-call proxy handles several observed Nemotron response-shape quirks, but OpenCode multi-step tool reliability is still experimental

---

Tech Aarvam  
Copyright (c) 2026 Tech Aarvam.  
Primary authors: Ram (Ramasubramanian B), Claude Code
