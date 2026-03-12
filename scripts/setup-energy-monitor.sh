#!/usr/bin/env bash
# ── OpenJarvis Energy Monitor Setup ───────────────────────────────────
# Installs the platform-appropriate energy monitoring extra so benchmarks
# and telemetry can report energy (Joules), power (Watts), and efficiency.
#
# Usage:
#   ./scripts/setup-energy-monitor.sh
#   # or from bench when energy monitor is missing:
#   jarvis bench -b energy  # prompts to run this script
# ──────────────────────────────────────────────────────────────────────

set -euo pipefail

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

info()  { echo -e "${BLUE}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Detect platform and choose extra
_detect_extra() {
  local os arch
  os=$(uname -s)
  arch=$(uname -m 2>/dev/null || echo "")

  case "$os" in
    Darwin)
      if [ "$arch" = "arm64" ]; then
        echo "energy-apple"   # zeus-ml[apple] for Apple Silicon
      else
        echo ""
      fi
      ;;
    Linux)
      if command -v nvidia-smi &>/dev/null; then
        echo "gpu-metrics"    # pynvml for NVIDIA
      elif [ -d /sys/class/powercap ] && [ -n "$(ls -A /sys/class/powercap 2>/dev/null)" ]; then
        echo ""               # RAPL built-in, no extra
      elif command -v rocm-smi &>/dev/null; then
        echo "energy-amd"     # amdsmi for AMD
      else
        echo ""
      fi
      ;;
    *)
      echo ""
      ;;
  esac
}

# Check if energy monitor is already usable (use uv run when in project)
_check_installed() {
  local py_cmd="python3"
  if command -v uv &>/dev/null && [ -f "pyproject.toml" ]; then
    py_cmd="uv run python"
  fi
  $py_cmd -c "
try:
    from openjarvis.telemetry.energy_monitor import create_energy_monitor
    m = create_energy_monitor()
    if m is not None:
        print('ok')
    else:
        print('missing')
except Exception:
    print('missing')
" 2>/dev/null || echo "missing"
}

echo -e "${BOLD}"
echo "  ┌──────────────────────────────────┐"
echo "  │   OpenJarvis Energy Monitor Setup │"
echo "  └──────────────────────────────────┘"
echo -e "${NC}"

# Already working?
if [ "$(_check_installed)" = "ok" ]; then
  ok "Energy monitor already available."
  exit 0
fi

EXTRA="$( _detect_extra )"

if [ -z "$EXTRA" ]; then
  case "$(uname -s)" in
    Darwin)
      if [ "$(uname -m)" != "arm64" ]; then
        warn "No energy monitor for Intel Macs."
      else
        warn "Could not detect Apple Silicon energy monitor."
        info "Try: uv pip install 'openjarvis[energy-apple]'"
      fi
      ;;
    Linux)
      info "RAPL (Intel/AMD CPU) may work without extras — check /sys/class/powercap"
      info "For NVIDIA: uv pip install 'openjarvis[gpu-metrics]'"
      info "For AMD: uv pip install 'openjarvis[energy-amd]'"
      ;;
    *)
      warn "Unsupported platform for energy monitoring."
      ;;
  esac
  exit 1
fi

# Install
info "Installing openjarvis[$EXTRA]..."
if command -v uv &>/dev/null; then
  if [ -f "pyproject.toml" ]; then
    uv sync --extra "$EXTRA" --quiet 2>/dev/null || uv sync --extra "$EXTRA"
  else
    uv pip install "openjarvis[$EXTRA]"
  fi
  ok "Installed openjarvis[$EXTRA]"
else
  warn "uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  info "Then run: uv pip install 'openjarvis[$EXTRA]'"
  exit 1
fi

# Verify
if [ "$(_check_installed)" = "ok" ]; then
  ok "Energy monitor ready. Run 'jarvis bench -b energy' to verify."
else
  warn "Install completed but energy monitor still unavailable."
  info "Run 'jarvis doctor' for diagnostics."
  exit 1
fi
