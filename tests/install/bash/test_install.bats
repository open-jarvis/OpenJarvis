#!/usr/bin/env bats

setup() {
    TEST_TMPDIR=$(mktemp -d)
    export FAKE_HOME="$TEST_TMPDIR/home"
    mkdir -p "$FAKE_HOME"
    export HOME="$FAKE_HOME"
    export OPENJARVIS_HOME="$FAKE_HOME/.openjarvis"

    export STUBS_DIR="$BATS_TEST_DIRNAME/stubs"
    # Use a copy of stubs without uv-style real binaries that might be on the host.
    # Just put our stubs first in PATH.
    export PATH="$STUBS_DIR:/usr/bin:/bin"

    export GIT_STUB_LOG="$TEST_TMPDIR/git.log"
    export OLLAMA_STUB_LOG="$TEST_TMPDIR/ollama.log"
    export UV_STUB_LOG="$TEST_TMPDIR/uv.log"
    export CURL_STUB_LOG="$TEST_TMPDIR/curl.log"
    : > "$GIT_STUB_LOG"
    : > "$OLLAMA_STUB_LOG"
    : > "$UV_STUB_LOG"
    : > "$CURL_STUB_LOG"

    # uv stub needs to fake creating a venv with a jarvis binary.
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
            cat > "\$venv_path/bin/jarvis" <<'EOJ'
#!/usr/bin/env bash
# fake jarvis for tests
echo "fake jarvis: \$@"
exit 0
EOJ
            chmod +x "\$venv_path/bin/jarvis"
            cat > "\$venv_path/bin/python" <<'EOJ'
#!/usr/bin/env bash
# fake python that prints empty for the inline embedded scripts (recommend_model, etc.)
exit 0
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

@test "creates ~/.openjarvis directory tree" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -d "$OPENJARVIS_HOME/src" ]
    [ -d "$OPENJARVIS_HOME/.state" ]
    [ -d "$OPENJARVIS_HOME/.scripts" ]
}

@test "writes install-state.json on success" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -f "$OPENJARVIS_HOME/.state/install-state.json" ]
}

@test "calls git clone for the OpenJarvis repo" {
    run bash "$SCRIPT" --no-bg-orchestrator
    grep -q "clone" "$GIT_STUB_LOG"
}

@test "creates jarvis symlink in ~/.local/bin" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -L "$FAKE_HOME/.local/bin/jarvis" ] || [ -f "$FAKE_HOME/.local/bin/jarvis" ]
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
    OPENJARVIS_FORCE_WSL=1 run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    grep -q "wsl" "$OPENJARVIS_HOME/.state/install-state.json"
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
