#!/usr/bin/env bats

setup() {
    TEST_TMPDIR=$(mktemp -d)
    export OPENJARVIS_HOME="$TEST_TMPDIR/.openjarvis"
    mkdir -p "$OPENJARVIS_HOME/.state"
    mkdir -p "$OPENJARVIS_HOME/src/rust/crates/openjarvis-python"
    touch "$OPENJARVIS_HOME/src/rust/crates/openjarvis-python/Cargo.toml"
    export UV_STUB_LOG="$TEST_TMPDIR/uv.log"
    : > "$UV_STUB_LOG"
    export PATH="$BATS_TEST_DIRNAME/stubs:$PATH"
    export SCRIPT="$BATS_TEST_DIRNAME/../../../scripts/install/build-extension.sh"
}

teardown() {
    [[ -n "${TEST_TMPDIR:-}" ]] && rm -rf "$TEST_TMPDIR"
}

@test "writes extension-built marker on success" {
    UV_STUB_EXIT=0 run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    [ -f "$OPENJARVIS_HOME/.state/extension-built" ]
}

@test "writes extension-failed marker on failure" {
    UV_STUB_EXIT=1 run bash "$SCRIPT"
    [ "$status" -ne 0 ]
    [ -f "$OPENJARVIS_HOME/.state/extension-failed" ]
    [ -s "$OPENJARVIS_HOME/.state/extension-failed" ]
}

@test "removes prior failed marker on success" {
    touch "$OPENJARVIS_HOME/.state/extension-failed"
    UV_STUB_EXIT=0 run bash "$SCRIPT"
    [ ! -f "$OPENJARVIS_HOME/.state/extension-failed" ]
    [ -f "$OPENJARVIS_HOME/.state/extension-built" ]
}

@test "calls uv run maturin develop with the right manifest" {
    UV_STUB_EXIT=0 run bash "$SCRIPT"
    grep -q "run maturin develop -m" "$UV_STUB_LOG"
    grep -q "rust/crates/openjarvis-python/Cargo.toml" "$UV_STUB_LOG"
}

@test "atomic rename — no .tmp file left behind" {
    UV_STUB_EXIT=0 run bash "$SCRIPT"
    leftover=$(find "$OPENJARVIS_HOME/.state" -name "*.tmp" 2>/dev/null | wc -l)
    [ "$leftover" -eq 0 ]
}
