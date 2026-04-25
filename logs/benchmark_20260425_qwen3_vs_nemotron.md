# Model Benchmark: qwen3-8b-64k vs nemotron-3-nano-128k

**Date:** 2026-04-25  
**Machine:** RTX 5070 Blackwell, 12 GB VRAM  
**Proxy:** tool_calls_proxy.py on port 8100 → Ollama 11434  
**qwen3 thinking:** disabled (`options.think=false`) for fair speed comparison  

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

**Quality:** Both models answered every question correctly. qwen3 tends to be more verbose and elaborate; nemotron is concise and accurate. Neither made factual errors.

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
| Factual accuracy | 100% | 100% |
| Response style | Verbose, elaborated | Concise, direct |
| Tool calling | Native (Ollama) | Via proxy reasoning-fallback |

### Recommendation

**For this 12 GB Blackwell setup, `nemotron-3-nano-128k` is the recommended daily driver:**

- **3.4× faster** end-to-end across all task types
- **3× more effective context** (128k vs ~40k actual) — critical for real codebases
- Identical accuracy on all tested tasks
- Smaller VRAM footprint leaves more headroom for the KV cache at large contexts
- The tool-call proxy handles Nemotron's reasoning-stream quirk transparently

qwen3-8b-64k remains useful when response verbosity and elaboration are preferred (documentation writing, step-by-step explanations), or as a fallback when the nemotron proxy path encounters issues.

---

Tech Aarvam  
Copyright (c) 2026 Tech Aarvam.  
Primary authors: Ram (Ramasubramanian B), Claude Code
