#!/usr/bin/env bash
# install.sh — OpenJarvis curl-pipe-bash installer.
#
# Usage:
#   curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash
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

# ---- non-WSL Windows refusal ----
# Running the installer in Git Bash / MSYS2 / Cygwin on native Windows
# (i.e. NOT inside WSL2) gets the user into a confusing failure state:
# uv/git tooling installs to Windows paths the rest of OpenJarvis can't
# reach, and Ollama integration silently breaks. The supported Windows
# path is WSL2. Bail early with a clear next step rather than letting
# users discover this 3 minutes into a doomed install.
case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*)
        cat >&2 <<'EOF'
install.sh: native Windows (Git Bash / MSYS2 / Cygwin) is not supported.

OpenJarvis runs on Windows via WSL2. Two paths:

  1. WSL2 (recommended for the CLI). One-time setup in an admin PowerShell:

       wsl --install -d Ubuntu-24.04

     Open the Ubuntu shell that gets installed, then re-run:

       curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash

  2. Desktop app — download the .exe from the Releases page:
     https://github.com/open-jarvis/OpenJarvis/releases

See the WSL2 install guide for the full walkthrough:
  https://open-jarvis.github.io/OpenJarvis/getting-started/wsl2/
EOF
        exit 1
        ;;
esac

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
#
# `git` and `curl` are the only host tools we require. On the supported
# platforms we can auto-install both; if that fails we fall back to a
# clear "here's the exact command" error rather than a generic refusal.
need() {
    if command -v "$1" >/dev/null 2>&1; then
        return 0
    fi
    case "$(uname -s)" in
        Darwin)  bootstrap_macos_tool "$1" ;;
        Linux)   bootstrap_linux_tool "$1" ;;
        *)       fail_missing_tool "$1" ;;
    esac
}

bootstrap_macos_tool() {
    local tool="$1"
    # On macOS, git AND curl ship as part of the Xcode Command Line Tools.
    # `xcode-select --install` opens a system dialog — useless in a
    # headless SSH session, so refuse fast there rather than polling for
    # 20 minutes against something that will never arrive.
    if [[ -z "${SSH_TTY:-}${SSH_CONNECTION:-}" ]]; then
        :  # local GUI session — proceed
    else
        cat >&2 <<EOF
install.sh: '$tool' not found, and this looks like a headless SSH session
(SSH_CONNECTION is set). The xcode-select GUI installer can't run here.

Install '$tool' over SSH with one of:
  - From a GUI login: 'xcode-select --install' (then re-run this script)
  - Or: a third-party manager — Homebrew / MacPorts / nix

Re-run this script once '$tool' is on PATH.
EOF
        exit 1
    fi
    echo "install.sh: '$tool' not found — installing Xcode Command Line Tools (provides git + curl)..."
    echo "  A system dialog will open. Click 'Install' and accept the license."
    xcode-select --install 2>/dev/null || true
    local waited=0
    while ! command -v "$tool" >/dev/null 2>&1; do
        if (( waited >= 600 )); then  # 10 minutes
            echo "install.sh: timed out waiting for Xcode Command Line Tools."
            echo "  Finish the install via the dialog, then re-run this command."
            exit 1
        fi
        sleep 5
        waited=$((waited + 5))
        if (( waited % 60 == 0 )); then
            echo "  …still waiting for '$tool' to appear (${waited}s)"
        fi
    done
    echo "  '$tool' installed."
}

bootstrap_linux_tool() {
    local tool="$1"
    # We need passwordless sudo (or already-root) — stdin is the curl
    # pipe, so an interactive password prompt will either hang or fail
    # silently under `set -euo pipefail`. Check up-front and fail with a
    # clear message rather than a confusing hang.
    if [[ "$(id -u)" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
        cat >&2 <<EOF
install.sh: '$tool' is not installed, and we need sudo to install it via
the system package manager — but sudo would prompt for a password and
stdin is occupied by the curl pipe.

Two ways forward:

  1. Install '$tool' yourself, then re-run this installer:
       Debian/Ubuntu: sudo apt install -y $tool
       Fedora/RHEL:   sudo dnf install -y $tool
       Arch:          sudo pacman -S $tool

  2. Pre-authenticate sudo before piping (caches credentials for 5 min):
       sudo -v && curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash
EOF
        exit 1
    fi
    local sudo=""
    [[ "$(id -u)" -ne 0 ]] && sudo="sudo"
    echo "install.sh: '$tool' not found — installing via the system package manager..."
    # Use `;` not `&&` between update and install so a transient apt
    # update failure (mirror flake, expired cache) doesn't block install
    # from a still-usable local index.
    if command -v apt-get >/dev/null 2>&1; then
        $sudo apt-get update -q || true
        $sudo apt-get install -y "$tool"
    elif command -v dnf >/dev/null 2>&1; then
        $sudo dnf install -y "$tool"
    elif command -v yum >/dev/null 2>&1; then
        $sudo yum install -y "$tool"
    elif command -v pacman >/dev/null 2>&1; then
        $sudo pacman -S --noconfirm "$tool"
    elif command -v zypper >/dev/null 2>&1; then
        $sudo zypper install -y "$tool"
    elif command -v apk >/dev/null 2>&1; then
        $sudo apk add --no-cache "$tool"
    else
        fail_missing_tool "$tool"
    fi
    if ! command -v "$tool" >/dev/null 2>&1; then
        fail_missing_tool "$tool"
    fi
}

fail_missing_tool() {
    cat >&2 <<EOF
install.sh: '$1' is required but not found and we couldn't install it automatically.

Install hints:
  macOS:         xcode-select --install (provides git, curl)
  Debian/Ubuntu: sudo apt install $1
  Fedora/RHEL:   sudo dnf install $1
  Arch:          sudo pacman -S $1

Re-run this script once '$1' is on PATH.
EOF
    exit 1
}

need git
need curl

# ---- python command ----
# Prefer `python3` (Linux / macOS / WSL convention); fall back to `python`
# on minimal distros that only ship the unversioned name. This is used by
# the analytics beacon and state-file helpers below — uv installs its own
# interpreter into the venv later, so this is only for the bootstrap shims.
PY_CMD="python3"
if ! command -v python3 >/dev/null 2>&1; then
    if command -v python >/dev/null 2>&1; then
        PY_CMD="python"
    fi
fi

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

# ---- analytics beacon (anonymized install funnel) ----
#
# Posts a small JSON event to PostHog at each install stage so the
# OpenJarvis team can see where users drop off during install.
# No content, no IPs (handled by PostHog disable_geoip on server),
# no hardware identifiers — just OS, arch, elapsed time, and stage name.
#
ANALYTICS_HOST="${OPENJARVIS_ANALYTICS_HOST:-https://34.231.106.201.sslip.io}"
ANALYTICS_KEY="${OPENJARVIS_ANALYTICS_KEY:-phc_ysKu72QaxzYNmDpHFcesD2ZZAe68zkdWJEKoYYkc5e3n}"
ANON_ID_FILE="$OPENJARVIS_HOME/anon_id"
INSTALL_START_EPOCH="$(date +%s)"
CURRENT_STAGE=""

analytics_enabled() {
    return 0
}

detect_os() {
    case "$(uname -s)" in
        Darwin) echo "darwin" ;;
        Linux) [[ "$WSL" -eq 1 ]] && echo "wsl" || echo "linux" ;;
        *) echo "unknown" ;;
    esac
}

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64) echo "x86_64" ;;
        arm64|aarch64) echo "arm64" ;;
        *) echo "unknown" ;;
    esac
}

get_anon_id() {
    if [[ -f "$ANON_ID_FILE" ]]; then
        cat "$ANON_ID_FILE"
        return
    fi
    local new_id
    new_id="$("$PY_CMD" -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || echo "")"
    if [[ -z "$new_id" ]]; then
        return
    fi
    echo "$new_id" > "$ANON_ID_FILE"
    echo "$new_id"
}

stage_label() {
    case "$1" in
        install_uv) echo "uv" ;;
        clone_repo|copy_scripts) echo "deps" ;;
        create_venv) echo "venv" ;;
        editable_install) echo "package" ;;
        install_ollama|start_ollama) echo "ollama" ;;
        pull_default_model) echo "model_download" ;;
        write_config) echo "config" ;;
        install_symlinks|ensure_path|detach_bg_orchestrator) echo "verify" ;;
        *) echo "" ;;
    esac
}

beacon() {
    # Args: event_name stage_label elapsed_ms exit_code
    local event="$1"
    local stage="${2:-}"
    local elapsed_ms="${3:-0}"
    local exit_code="${4:-0}"

    if ! analytics_enabled; then
        return 0
    fi

    local anon_id os arch
    anon_id="$(get_anon_id)"
    if [[ -z "$anon_id" ]]; then
        return 0
    fi
    os="$(detect_os)"
    arch="$(detect_arch)"

    "$PY_CMD" - "$ANALYTICS_HOST" "$ANALYTICS_KEY" "$event" "$anon_id" \
        "$os" "$arch" "$stage" "$elapsed_ms" "$exit_code" \
        >/dev/null 2>&1 <<'PYEOF' || true
import json
import sys
import urllib.request

host, key, event, distinct_id, os_val, arch, stage, elapsed_ms, exit_code = sys.argv[1:10]
props = {
    "os": os_val,
    "arch": arch,
    "installer_version": "0.1.1",
}
if stage:
    props["stage"] = stage
if elapsed_ms and elapsed_ms != "0":
    try:
        props["elapsed_ms"] = int(elapsed_ms)
    except ValueError:
        pass
if exit_code and exit_code != "0":
    try:
        props["exit_code"] = int(exit_code)
    except ValueError:
        pass
if event == "install_completed":
    props["total_elapsed_ms"] = props.pop("elapsed_ms", 0)
payload = {
    "api_key": key,
    "event": event,
    "distinct_id": distinct_id,
    "properties": props,
}
req = urllib.request.Request(
    f"{host}/i/v0/e/",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    urllib.request.urlopen(req, timeout=5)
except Exception:
    pass
PYEOF
}

_on_install_error() {
    local exit_code=$?
    beacon "install_failed" "$(stage_label "$CURRENT_STAGE")" 0 "$exit_code"
    exit "$exit_code"
}
trap _on_install_error ERR

# ---- helpers ----
state_done() {
    [[ -f "$STATE_FILE" ]] && grep -q "\"$1\":[[:space:]]*true" "$STATE_FILE"
}

mark_done() {
    if [[ ! -f "$STATE_FILE" ]]; then
        echo '{}' > "$STATE_FILE"
    fi
    "$PY_CMD" - "$STATE_FILE" "$1" "$WSL" <<'PYEOF'
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
    CURRENT_STAGE="$name"
    if [[ "$FORCE" -ne 1 ]] && state_done "$name"; then
        echo "[ok] $desc (already done)"
        return 0
    fi
    echo "[..] $desc"
    local stage_start_epoch stage_elapsed_ms
    stage_start_epoch="$(date +%s)"
    "$@"
    mark_done "$name"
    stage_elapsed_ms=$(( ( $(date +%s) - stage_start_epoch ) * 1000 ))
    beacon "install_stage_completed" "$(stage_label "$name")" "$stage_elapsed_ms"
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
    # `uv venv --python 3.11` fails on hosts that don't have Python 3.11
    # installed at all (fresh macOS without xcode-select, fresh Ubuntu
    # 24.04 which only ships 3.12, etc). uv can bootstrap its own
    # interpreter — use that path so the user never has to pre-install
    # Python.
    #
    # We capture stderr to a log file instead of /dev/null so a genuine
    # failure (disk full, broken venv dir, permission denied) is still
    # surfaceable when the bootstrap fallback ultimately fails.
    local err_log="$STATE_DIR/venv-create.err"
    if ! uv venv --python 3.11 "$VENV_DIR" 2>"$err_log"; then
        echo "    No system Python 3.11 — uv will download a managed one..."
        uv python install 3.11
        if ! uv venv --python 3.11 "$VENV_DIR"; then
            echo "    venv creation failed. First attempt's stderr:"
            sed 's/^/      /' "$err_log" >&2
            return 1
        fi
    fi
    rm -f "$err_log"
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
        wait_for_ollama || true
        return 0
    fi
    if [[ "$WSL" -eq 1 ]] || ! command -v systemctl >/dev/null 2>&1; then
        nohup ollama serve > "$STATE_DIR/ollama.log" 2>&1 &
    else
        systemctl --user start ollama 2>/dev/null \
            || nohup ollama serve > "$STATE_DIR/ollama.log" 2>&1 &
    fi
    # `|| true` is load-bearing — wait_for_ollama returns 1 on timeout
    # and we're under `set -euo pipefail` via the `step` wrapper. We want
    # the warning to surface in the final banner, not abort the install.
    wait_for_ollama || true
}

# Poll `ollama list` until the daemon responds, up to 60 seconds. Replaces
# the old fixed `sleep 1` which raced the model pull on slower hosts.
# Cold-start latency on low-spec ARM boards or under heavy load can run
# past 30s; 60 is the conservative ceiling. Returns 1 on timeout — caller
# MUST guard with `|| true` (see start_ollama).
wait_for_ollama() {
    local waited=0
    while ! ollama list >/dev/null 2>&1; do
        if (( waited >= 60 )); then
            echo "    warning: ollama daemon not responding after 60s — check $STATE_DIR/ollama.log"
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
}

# Tracks whether the foreground model pull actually succeeded. If it
# didn't, the final completion banner needs to say so loudly rather than
# claiming chat is ready.
MODEL_PULL_OK=0

pull_default_model() {
    if [[ "$MINIMAL" -eq 1 ]]; then
        echo "    --minimal set; skipping model pull"
        MODEL_PULL_OK=1  # nothing to pull → not a failure
        return 0
    fi
    if ollama pull qwen3.5:2b; then
        MODEL_PULL_OK=1
    else
        echo "    warning: ollama pull failed; bg-orchestrator will retry in the background"
    fi
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

# Tracks whether the user needs to source ~/.bashrc / ~/.zshrc / open a
# new terminal before `jarvis` will resolve. Set only when ensure_path
# actually modified the user's rc file.
PATH_MODIFIED=0

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
        # rc already has our PATH line from a prior install; just remind.
        PATH_MODIFIED=1
        PATH_MODIFIED_RC="$rc"
        return 0
    fi
    {
        echo ''
        echo '# OpenJarvis'
        echo 'export PATH="$HOME/.local/bin:$PATH"'
    } >> "$rc"
    PATH_MODIFIED=1
    PATH_MODIFIED_RC="$rc"
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

beacon "install_started"

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

# Total install duration → install_completed event.
INSTALL_TOTAL_MS=$(( ( $(date +%s) - INSTALL_START_EPOCH ) * 1000 ))
beacon "install_completed" "" "$INSTALL_TOTAL_MS"
# Clear ERR trap — we succeeded; any later non-zero exit shouldn't beacon a failure.
trap - ERR

echo
echo "Done."
echo

# Tell the truth about what the user has to do next, given (a) whether
# the foreground model pull actually succeeded and (b) whether the PATH
# update needs a shell refresh. The four combinations:
#
#   PATH ok + model ok   -> "type jarvis"
#   PATH new + model ok  -> "source rc && jarvis  (or open new terminal)"
#   PATH ok + model bad  -> "model still downloading; jarvis doctor"
#   PATH new + model bad -> "source rc && jarvis doctor; chat works once download finishes"
#
# `jarvis` and `jarvis doctor` need PATH equally, so the source/restart
# guidance goes first when PATH was modified.
NEXT_CMD="jarvis"
if [[ "$MODEL_PULL_OK" -ne 1 ]]; then
    NEXT_CMD="jarvis doctor"
fi

if [[ "$PATH_MODIFIED" -eq 1 ]]; then
    cat <<EOF
A PATH update was written to ${PATH_MODIFIED_RC:-your shell rc file}. To
pick it up in THIS terminal:

  source ${PATH_MODIFIED_RC:-~/.bashrc} && $NEXT_CMD

Or open a new terminal and run: $NEXT_CMD

EOF
else
    cat <<EOF
Run: $NEXT_CMD

EOF
fi

if [[ "$MODEL_PULL_OK" -ne 1 ]]; then
    cat <<EOF
NOTE: the qwen3.5:2b model didn't finish downloading. 'jarvis doctor'
shows the retry progress; chat will work once the download completes
in the background.

EOF
fi

cat <<EOF
Background work continues silently:
  - Rust toolchain + maturin extension build
  - Bigger model downloads
  Run 'jarvis doctor' to check status anytime.
EOF
