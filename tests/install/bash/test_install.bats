#!/usr/bin/env bats

# Requires Python with tomlkit, as does the installed application. Set
# FRIDAY_AI_TEST_PYTHON to an existing project venv when running locally.

setup() {
    export FRIDAY_AI_TEST_PYTHON="${FRIDAY_AI_TEST_PYTHON:-$(command -v python3)}"
    export PYTHONPATH="$BATS_TEST_DIRNAME/../../../src"
    unset FRIDAY_AI_CONFIG XDG_DATA_HOME
    TEST_TMPDIR=$(mktemp -d)
    export FAKE_HOME="$TEST_TMPDIR/home"
    mkdir -p "$FAKE_HOME"
    export HOME="$FAKE_HOME"
    export FRIDAY_AI_HOME="$FAKE_HOME/.friday_ai"

    export STUBS_DIR="$BATS_TEST_DIRNAME/stubs"
    # Use a copy of stubs without uv-style real binaries that might be on the host.
    # Just put our stubs first in PATH.
    export PATH="$STUBS_DIR:/usr/bin:/bin"

    export GIT_STUB_LOG="$TEST_TMPDIR/git.log"
    export OLLAMA_STUB_LOG="$TEST_TMPDIR/ollama.log"
    export UV_STUB_LOG="$TEST_TMPDIR/uv.log"
    export CURL_STUB_LOG="$TEST_TMPDIR/curl.log"
    export FRIDAY_STUB_LOG="$TEST_TMPDIR/friday.log"
    : > "$GIT_STUB_LOG"
    : > "$OLLAMA_STUB_LOG"
    : > "$UV_STUB_LOG"
    : > "$CURL_STUB_LOG"

    # uv stub needs to fake creating a venv with a friday binary.
    # Replace the stubs/uv with one that creates the venv tree on `venv` command.
    # Since we don't want to mutate the real stub, override via a per-test stub dir.
    export PER_TEST_STUBS="$TEST_TMPDIR/stubs"
    mkdir -p "$PER_TEST_STUBS"
    cat "$STUBS_DIR/uv" > "$PER_TEST_STUBS/uv"
    chmod +x "$PER_TEST_STUBS/uv"
    # Wrap uv to handle 'venv' specially.
    cat > "$PER_TEST_STUBS/uv" <<EOF
#!/usr/bin/env bash
echo "\$@" >> "\$UV_STUB_LOG"
case "\$1" in
    venv)
        # uv venv [--python X.Y] <path>
        # Find the path arg (last non-flag).
        for a in "\$@"; do
            if [[ "\$a" != --* ]] && [[ "\$a" != -* ]] && [[ "\$a" != "venv" ]] && [[ ! "\$a" =~ ^[0-9]+\\.[0-9]+\$ ]]; then
                venv_path="\$a"
            fi
        done
        if [[ -n "\$venv_path" ]]; then
            mkdir -p "\$venv_path/bin"
            cat > "\$venv_path/bin/friday" <<'EOJ'
#!/usr/bin/env bash
# fake friday for tests
echo "\$@" >> "\$FRIDAY_STUB_LOG"
# Model the pre-consent CLI, which cannot validate the new schema key.
if [[ "\$*" == 'config set analytics.choice_recorded true' ]]; then
    echo "Error: Unknown config key: 'analytics.choice_recorded'" >&2
    exit 1
fi
echo "fake friday: \$@"
exit 0
EOJ
            chmod +x "\$venv_path/bin/friday"
            cat > "\$venv_path/bin/python" <<'EOJ'
#!/usr/bin/env bash
# Run the real persistence code using an interpreter with app dependencies.
exec "\$FRIDAY_AI_TEST_PYTHON" "\$@"
EOJ
            chmod +x "\$venv_path/bin/python"
        fi
        ;;
esac
exit 0
EOF
    chmod +x "$PER_TEST_STUBS/uv"

    # Copy other stubs, with the per-test uv first.
    cp "$STUBS_DIR"/{git,curl,ollama,cargo,rustup} "$PER_TEST_STUBS/"
    chmod +x "$PER_TEST_STUBS"/*

    export PATH="$PER_TEST_STUBS:/usr/bin:/bin"

    export SCRIPT="$BATS_TEST_DIRNAME/../../../scripts/install/install.sh"
}

teardown() {
    [[ -n "${TEST_TMPDIR:-}" ]] && rm -rf "$TEST_TMPDIR"
}

assert_analytics_preference() {
    "$FRIDAY_AI_TEST_PYTHON" - "$1" "$2" "$3" <<'PY'
import sys
from pathlib import Path

import tomlkit

analytics = tomlkit.parse(Path(sys.argv[1]).read_text())["analytics"]
assert bool(analytics["enabled"]) is (sys.argv[2] == "true")
assert bool(analytics.get("choice_recorded", False)) is (sys.argv[3] == "true")
PY
}

@test "unattended install sends no analytics and persists disabled" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
    [ ! -f "$FRIDAY_AI_HOME/anon_id" ]
    assert_analytics_preference "$FRIDAY_AI_HOME/config.toml" false false
}

@test "explicit analytics flag sends beacons and persists enabled" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --analytics
    [ "$status" -eq 0 ]
    grep -q '/i/v0/e/' "$CURL_STUB_LOG"
    [ -s "$FRIDAY_AI_HOME/anon_id" ]
    assert_analytics_preference "$FRIDAY_AI_HOME/config.toml" true true
}

@test "Enter at dedicated terminal prompt consents before the first beacon" {
    run python3 "$BATS_TEST_DIRNAME/run_installer_pty.py" "$SCRIPT" '["\n"]'
    [ "$status" -eq 0 ]
    [[ "$output" == *"Press Enter or Y to consent, or N to decline"* ]]
    grep -q '"event":"install_started"' "$CURL_STUB_LOG"
    assert_analytics_preference "$FRIDAY_AI_HOME/config.toml" true true
}

@test "N at terminal prompt declines every installer beacon" {
    run python3 "$BATS_TEST_DIRNAME/run_installer_pty.py" "$SCRIPT" '["N\n"]'
    [ "$status" -eq 0 ]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
    [ ! -f "$FRIDAY_AI_HOME/anon_id" ]
    assert_analytics_preference "$FRIDAY_AI_HOME/config.toml" false true
}

@test "invalid answer retries without silently consenting" {
    run python3 "$BATS_TEST_DIRNAME/run_installer_pty.py" "$SCRIPT" '["invalid\n", "n\n"]'
    [ "$status" -eq 0 ]
    [[ "$output" == *"Please press Enter, type Y, or type N."* ]]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
}

@test "terminal EOF is different from pressing Enter" {
    run python3 "$BATS_TEST_DIRNAME/run_installer_pty.py" "$SCRIPT" '["\u0004"]'
    [ "$status" -eq 0 ]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
    [ ! -f "$FRIDAY_AI_HOME/anon_id" ]
    assert_analytics_preference "$FRIDAY_AI_HOME/config.toml" false false
}

@test "declining on a rerun persists despite skipped config creation" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --analytics
    [ "$status" -eq 0 ]
    : > "$FRIDAY_STUB_LOG"
    : > "$CURL_STUB_LOG"
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --no-analytics
    [ "$status" -eq 0 ]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
    ! grep -q '_bootstrap' "$FRIDAY_STUB_LOG"
    assert_analytics_preference "$FRIDAY_AI_HOME/config.toml" false true
}

@test "rerun saves consent with an older CLI and preserves existing TOML" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    cat > "$FRIDAY_AI_HOME/config.toml" <<'TOML'
# Preserve user settings and comments.
[engine]
default = "ollama"
[analytics]
enabled = false # Previous choice.
flush_at_size = 7
TOML
    run "$FRIDAY_AI_HOME/.venv/bin/friday" config set analytics.choice_recorded true
    [ "$status" -eq 1 ]
    : > "$FRIDAY_STUB_LOG"
    : > "$UV_STUB_LOG"
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --analytics
    [ "$status" -eq 0 ]
    [ ! -s "$UV_STUB_LOG" ]
    [ ! -s "$FRIDAY_STUB_LOG" ]
    assert_analytics_preference "$FRIDAY_AI_HOME/config.toml" true true
    grep -q '# Preserve user settings and comments.' "$FRIDAY_AI_HOME/config.toml"
    grep -q '# Previous choice.' "$FRIDAY_AI_HOME/config.toml"
    grep -q 'default = "ollama"' "$FRIDAY_AI_HOME/config.toml"
    grep -q 'flush_at_size = 7' "$FRIDAY_AI_HOME/config.toml"
}

@test "consent respects FRIDAY_AI_CONFIG instead of changing the default config" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --no-analytics
    [ "$status" -eq 0 ]
    export FRIDAY_AI_CONFIG="$TEST_TMPDIR/custom config.toml"
    printf '# Custom config\n[engine]\ndefault = "ollama"\n' > "$FRIDAY_AI_CONFIG"
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --analytics
    [ "$status" -eq 0 ]
    assert_analytics_preference "$FRIDAY_AI_CONFIG" true true
    assert_analytics_preference "$FRIDAY_AI_HOME/config.toml" false true
    grep -q '# Custom config' "$FRIDAY_AI_CONFIG"
}

@test "consent follows the runtime XDG path when FRIDAY_AI_HOME is unset" {
    unset FRIDAY_AI_HOME
    export XDG_DATA_HOME="$TEST_TMPDIR/xdg data"
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --analytics
    [ "$status" -eq 0 ]
    assert_analytics_preference "$XDG_DATA_HOME/friday_ai/config.toml" true true
    [ ! -f "$HOME/.friday_ai/config.toml" ]
}

@test "contradictory analytics flags are rejected" {
    run bash "$SCRIPT" --analytics --no-analytics
    [ "$status" -eq 2 ]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
}

@test "refuses to run as root" {
    # EUID is readonly in bash, so we stub `id` to return uid 0 instead.
    local root_stubs="$TEST_TMPDIR/root_stubs"
    mkdir -p "$root_stubs"
    cp "$PER_TEST_STUBS"/* "$root_stubs/"
    cat > "$root_stubs/id" <<'IDEOF'
#!/usr/bin/env bash
if [[ "$1" == "-u" ]]; then echo 0; else echo "uid=0(root) gid=0(root) groups=0(root)"; fi
IDEOF
    chmod +x "$root_stubs/id"
    PATH="$root_stubs:/usr/bin:/bin" run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -ne 0 ]
    echo "$output" | grep -qi "root"
}

@test "creates ~/.friday_ai directory tree" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -d "$FRIDAY_AI_HOME/src" ]
    [ -d "$FRIDAY_AI_HOME/.state" ]
    [ -d "$FRIDAY_AI_HOME/.scripts" ]
}

@test "writes install-state.json on success" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -f "$FRIDAY_AI_HOME/.state/install-state.json" ]
}

@test "calls git clone for the FridayAI repo" {
    run bash "$SCRIPT" --no-bg-orchestrator
    grep -q "clone" "$GIT_STUB_LOG"
}

@test "creates friday symlink in ~/.local/bin" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -L "$FAKE_HOME/.local/bin/friday" ] || [ -f "$FAKE_HOME/.local/bin/friday" ]
}

@test "is idempotent — second run skips completed steps" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    : > "$GIT_STUB_LOG"
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    ! grep -q "clone" "$GIT_STUB_LOG"
}

@test "detects WSL2 and writes platform note to install-state" {
    FRIDAY_AI_FORCE_WSL=1 run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    grep -q "wsl" "$FRIDAY_AI_HOME/.state/install-state.json"
}

@test "fails loudly when git is missing" {
    # Build a minimal stubs dir that has curl/uv/ollama but NO git.
    # We must NOT include /usr/bin or /bin in PATH because those dirs have real
    # git binaries on this system. Instead, provide only the commands the script
    # needs before it reaches the `need git` check (id, cat, bash).
    local no_git_stubs="$TEST_TMPDIR/no_git_stubs"
    mkdir -p "$no_git_stubs"
    for f in curl uv ollama cargo rustup; do
        cp "$PER_TEST_STUBS/$f" "$no_git_stubs/"
        chmod +x "$no_git_stubs/$f"
    done
    # Provide minimal system utilities (no git) using explicit symlinks.
    cat > "$no_git_stubs/id" <<'IDEOF'
#!/bin/bash
echo "1000"
IDEOF
    chmod +x "$no_git_stubs/id"
    ln -sf /bin/cat "$no_git_stubs/cat"
    ln -sf /bin/bash "$no_git_stubs/bash"
    PATH="$no_git_stubs" run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -ne 0 ]
    echo "$output" | grep -qi "git"
}

@test "--force re-runs completed steps" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    : > "$GIT_STUB_LOG"
    run bash "$SCRIPT" --no-bg-orchestrator --force
    [ "$status" -eq 0 ]
    # With --force, second run re-clones (clone is in git.log again).
    grep -q "clone" "$GIT_STUB_LOG"
}

@test "--minimal skips foreground model pull" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    # Ollama 'pull' should NOT have been called.
    if [ -s "$OLLAMA_STUB_LOG" ]; then
        ! grep -q "^pull " "$OLLAMA_STUB_LOG"
    fi
}

@test "install succeeds with no system Python on PATH (#484)" {
    # Build a stubs dir with NO python3 / python — verifies the
    # bootstrap shims (get_anon_id, beacon, mark_done) are Python-free.
    local no_py_stubs="$TEST_TMPDIR/no_py_stubs"
    mkdir -p "$no_py_stubs"
    for f in git curl uv ollama cargo rustup; do
        cp "$PER_TEST_STUBS/$f" "$no_py_stubs/"
        chmod +x "$no_py_stubs/$f"
    done
    # Provide minimal core utilities the shims need (od, sed, awk, tr, grep).
    for util in id cat bash sh head tail awk sed grep od tr cut mv rm mkdir cp chmod ln test pgrep date sleep ps; do
        if [[ -x "/usr/bin/$util" ]]; then
            ln -sf "/usr/bin/$util" "$no_py_stubs/$util"
        elif [[ -x "/bin/$util" ]]; then
            ln -sf "/bin/$util" "$no_py_stubs/$util"
        fi
    done
    # pgrep may be absent on minimal BusyBox/Alpine hosts; stub it as
    # "no matching process" so start_ollama's existing-daemon check
    # falls through to the spawn path (which the ollama stub handles).
    if [[ ! -x "$no_py_stubs/pgrep" ]]; then
        printf '#!/bin/sh\nexit 1\n' > "$no_py_stubs/pgrep"
        chmod +x "$no_py_stubs/pgrep"
    fi
    PATH="$no_py_stubs" run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    # State file was still written (mark_done is Python-free).
    [ -f "$FRIDAY_AI_HOME/.state/install-state.json" ]
    # And it still has valid-looking JSON for state_done's grep.
    grep -q '"install_uv":' "$FRIDAY_AI_HOME/.state/install-state.json"
}

@test "mark_done is idempotent — second mark of same key doesn't duplicate" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    # Capture first state file
    local first_count
    first_count="$(grep -c '"install_uv":' "$FRIDAY_AI_HOME/.state/install-state.json")"
    [ "$first_count" -eq 1 ]
    # Second run reuses state — keys should not duplicate even if some path re-marks.
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    local second_count
    second_count="$(grep -c '"install_uv":' "$FRIDAY_AI_HOME/.state/install-state.json")"
    [ "$second_count" -eq 1 ]
}

@test "create_venv picks newest in requires-python range, not hardcoded 3.11 (#476)" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    # uv stub logs every invocation. We should see `venv --python 3.13 ...`
    # (the upper bound of >=3.10,<3.14 is 3.14, so the highest usable is 3.13).
    grep -q '^venv --python 3.13' "$UV_STUB_LOG"
}
