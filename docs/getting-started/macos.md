# macOS Install

```bash
curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash
```

Works on Intel and Apple Silicon. The installer auto-detects your CPU/GPU.

## Prerequisites

If you've never run `git` or `curl` on this Mac, macOS will prompt you to install the Xcode Command Line Tools the first time you run them. Accept the prompt; that gives you both.

If you'd rather pre-install:

```bash
xcode-select --install
```

## Apple Silicon notes

- The installer picks `mlx` as the recommended engine via the standard hardware-detect path, but the foreground default is still Ollama for compatibility. Switch later with `jarvis init --force` and pick `mlx` if you've installed `mlx-lm`.
- Unified memory is reported as "VRAM" by the installer — that's intentional; on Apple Silicon, system RAM is what GPU-accelerated models can use.

## Rapid-MLX on Apple Silicon

| Engine | Config key | Default host | API prefix |
|--------|------------|--------------|------------|
| Rapid-MLX | `rapidmlx` | `http://localhost:8000` | `/v1` |

Install with `pip install rapid-mlx`, then start
`rapid-mlx serve mlx-community/Qwen3.5-4B-MLX-4bit`.
Run `jarvis init --engine rapidmlx` to select it, or set
`default = "rapidmlx"` under `[engine]` in your configuration.

## See also

- [Full installer reference](install.md)
