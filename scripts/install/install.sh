#!/usr/bin/env bash
# install.sh — OpenJarvis curl-pipe-bash installer.
#
# Usage:
#   curl -fsSL https://openjarvis.ai/install.sh | bash
#
# Flags (only used in tests / power users):
#   --no-bg-orchestrator   Skip the detached background orchestrator
#   --minimal              Skip foreground model pull (no `qwen3.5:2b`)
#   --force                Re-run all steps even if state file says done
#
# Environment overrides:
#   OPENJARVIS_HOME        Install dir (default: $HOME/.openjarvis)
#   OPENJARVIS_REPO_URL    git repo URL (default: https://github.com/open-jarvis/OpenJarvis.git)
#   OPENJARVIS_FORCE_WSL   Set 1 to force WSL detection (testing)

set -euo pipefail

# ---- args ----
SKIP_BG=0
MINIMAL=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --no-bg-orchestrator) SKIP_BG=1 ;;
        --minimal) MINIMAL=1 ;;
        --force) FORCE=1 ;;
        *) echo "install.sh: unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# ---- root refusal ----
if [[ "$(id -u)" -eq 0 ]]; then
    cat >&2 <<'EOF'
install.sh: don't run as root.

OpenJarvis installs to $HOME/.openjarvis, not /usr/local. Re-run as your
regular user (without sudo).
EOF
    exit 1
fi

# ---- prereq probe ----
need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        cat >&2 <<EOF
install.sh: '$1' is required but not found.

Install hints:
  macOS:        xcode-select --install (provides git, curl)
  Debian/Ubuntu: sudo apt install git curl
  Fedora/RHEL:   sudo dnf install git curl
  Arch:          sudo pacman -S git curl
EOF
        exit 1
    fi
}
need git
need curl

# ---- env ----
OPENJARVIS_HOME="${OPENJARVIS_HOME:-$HOME/.openjarvis}"
OPENJARVIS_REPO_URL="${OPENJARVIS_REPO_URL:-https://github.com/open-jarvis/OpenJarvis.git}"
SRC_DIR="$OPENJARVIS_HOME/src"
VENV_DIR="$OPENJARVIS_HOME/.venv"
STATE_DIR="$OPENJARVIS_HOME/.state"
SCRIPTS_DIR="$OPENJARVIS_HOME/.scripts"
STATE_FILE="$STATE_DIR/install-state.json"

mkdir -p "$OPENJARVIS_HOME" "$STATE_DIR" "$SCRIPTS_DIR"

# ---- WSL detection ----
WSL=0
if [[ "${OPENJARVIS_FORCE_WSL:-0}" == "1" ]]; then
    WSL=1
elif [[ -f /proc/sys/kernel/osrelease ]] && grep -qi "microsoft" /proc/sys/kernel/osrelease 2>/dev/null; then
    WSL=1
fi

# ---- helpers ----
state_done() {
    [[ -f "$STATE_FILE" ]] && grep -q "\"$1\":[[:space:]]*true" "$STATE_FILE"
}

mark_done() {
    if [[ ! -f "$STATE_FILE" ]]; then
        echo '{}' > "$STATE_FILE"
    fi
    python3 - "$STATE_FILE" "$1" "$WSL" <<'PYEOF'
import json, sys
path, key, wsl = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    data = json.load(f)
data[key] = True
data["wsl"] = bool(int(wsl))
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF
}

step() {
    local name="$1" desc="$2"; shift 2
    if [[ "$FORCE" -ne 1 ]] && state_done "$name"; then
        echo "[ok] $desc (already done)"
        return 0
    fi
    echo "[..] $desc"
    "$@"
    mark_done "$name"
    echo "[ok] $desc"
}

# ---- step impls ----
install_uv() {
    if command -v uv >/dev/null 2>&1; then
        echo "    uv already installed"
        return 0
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    if ! command -v uv >/dev/null 2>&1; then
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
}

clone_repo() {
    if [[ "$FORCE" -ne 1 ]] && [[ -d "$SRC_DIR/.git" ]]; then
        echo "    repo already at $SRC_DIR"
        return 0
    fi
    git clone --depth 1 "$OPENJARVIS_REPO_URL" "$SRC_DIR"
}

copy_scripts() {
    cp -f "$SRC_DIR"/scripts/install/*.sh "$SCRIPTS_DIR/"
    chmod +x "$SCRIPTS_DIR"/*.sh
}

create_venv() {
    uv venv --python 3.11 "$VENV_DIR"
}

editable_install() {
    cd "$SRC_DIR"
    uv pip install --python "$VENV_DIR/bin/python" -e .
}

install_ollama() {
    if command -v ollama >/dev/null 2>&1; then
        echo "    ollama already installed"
        return 0
    fi
    curl -fsSL https://ollama.com/install.sh | sh
}

start_ollama() {
    if pgrep -f "ollama serve" >/dev/null 2>&1; then
        echo "    ollama serve already running"
        return 0
    fi
    if [[ "$WSL" -eq 1 ]] || ! command -v systemctl >/dev/null 2>&1; then
        nohup ollama serve > "$STATE_DIR/ollama.log" 2>&1 &
        sleep 1
    else
        systemctl --user start ollama 2>/dev/null \
            || (nohup ollama serve > "$STATE_DIR/ollama.log" 2>&1 & sleep 1)
    fi
}

pull_default_model() {
    if [[ "$MINIMAL" -eq 1 ]]; then
        echo "    --minimal set; skipping model pull"
        return 0
    fi
    ollama pull qwen3.5:2b || echo "    warning: ollama pull failed; bg-orchestrator will retry"
}

write_config() {
    "$VENV_DIR/bin/jarvis" _bootstrap --write-config \
        --engine ollama --model qwen3.5:2b \
        --prefer-cloud-when-available
}

install_symlinks() {
    mkdir -p "$HOME/.local/bin"
    ln -sf "$SCRIPTS_DIR/jarvis-wrapper.sh" "$HOME/.local/bin/jarvis"
    ln -sf "$SCRIPTS_DIR/jarvis-uninstall.sh" "$HOME/.local/bin/jarvis-uninstall"
}

ensure_path() {
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) return 0 ;;
    esac
    local rc=""
    if [[ "$SHELL" == */zsh ]]; then
        rc="$HOME/.zshrc"
    else
        rc="$HOME/.bashrc"
    fi
    if grep -q "OpenJarvis" "$rc" 2>/dev/null; then
        return 0
    fi
    {
        echo ''
        echo '# OpenJarvis'
        echo 'export PATH="$HOME/.local/bin:$PATH"'
    } >> "$rc"
    echo "    Added ~/.local/bin to PATH in $rc — run: source $rc"
}

detach_bg_orchestrator() {
    if [[ "$SKIP_BG" -eq 1 ]]; then
        echo "    --no-bg-orchestrator set; skipping detach"
        return 0
    fi
    local models
    models=$("$VENV_DIR/bin/python" - <<'PYEOF' 2>/dev/null || true
from openjarvis.core.config import detect_hardware, recommend_model
hw = detect_hardware()
tier = recommend_model(hw, "ollama")
TIERS = ["qwen3.5:2b", "qwen3.5:4b", "qwen3.5:9b", "qwen3.5:27b"]
out = set([tier]) if tier else set()
if tier in TIERS:
    idx = TIERS.index(tier)
    if idx + 1 < len(TIERS):
        out.add(TIERS[idx + 1])
print(" ".join(sorted(out)))
PYEOF
    )
    if [[ -z "$models" ]]; then
        models=""
    fi
    nohup "$SCRIPTS_DIR/bg-orchestrator.sh" $models \
        > "$STATE_DIR/bg-orchestrator.log" 2>&1 &
    disown
}

# ---- run ----
echo "OpenJarvis installer"
echo "  install dir: $OPENJARVIS_HOME"
echo "  WSL2:        $WSL"
echo

step install_uv         "Install uv"            install_uv
step clone_repo         "Clone OpenJarvis repo" clone_repo
step copy_scripts       "Copy install scripts"  copy_scripts
step create_venv        "Create venv"           create_venv
step editable_install   "Install OpenJarvis"    editable_install
step install_ollama     "Install Ollama"        install_ollama
step start_ollama       "Start Ollama daemon"   start_ollama
step pull_default_model "Pull qwen3.5:2b"       pull_default_model
step write_config       "Write config.toml"     write_config
step install_symlinks   "Install symlinks"      install_symlinks
step ensure_path        "Ensure PATH"           ensure_path
step detach_bg_orchestrator "Detach background work" detach_bg_orchestrator

cat <<EOF

Done. Type 'jarvis' to start chatting.

Background work continues silently:
  - Rust toolchain + maturin extension build
  - Bigger model downloads
  Run 'jarvis doctor' to check status anytime.
EOF
