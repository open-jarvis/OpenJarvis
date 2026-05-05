# Linux Install

```bash
curl -fsSL https://openjarvis.ai/install.sh | bash
```

Tested on: Ubuntu 22.04 / 24.04, Fedora 40, Debian 12, Arch.

## Prerequisites

Most distros ship `git` and `curl`. If yours doesn't:

```bash
# Debian / Ubuntu
sudo apt install git curl

# Fedora / RHEL
sudo dnf install git curl

# Arch
sudo pacman -S git curl
```

## NVIDIA / AMD GPU

The installer auto-detects via `nvidia-smi` / `rocm-smi`. Datacenter cards (A100, H100, MI300+) get vLLM as the recommended engine; consumer cards get Ollama (NVIDIA) or Lemonade (AMD).

## See also

- [Full installer reference](install.md)
