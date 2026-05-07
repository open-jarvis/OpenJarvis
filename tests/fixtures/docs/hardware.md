# Hardware Requirements

OpenJarvis auto-detects your hardware and picks a sensible model.

## GPU Acceleration

On NVIDIA GPUs OpenJarvis uses CUDA via vLLM or Ollama. On Apple Silicon it uses Metal via the MLX engine. AMD GPUs work through ROCm when vLLM is available.

## Running Without a GPU

Yes, OpenJarvis supports CPU-only mode. Use llama.cpp as the engine and pick a small model — the 4B model is recommended for speed on CPU. Larger models will load but tokens-per-second drops significantly.

## Memory

Rough guide for model memory footprint at Q4 quantization:
- 4B model: ~3 GB
- 8B model: ~5 GB
- 30B model: ~20 GB

Add roughly 2 GB for OS and context.
