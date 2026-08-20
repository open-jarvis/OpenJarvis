#!/usr/bin/env bats
# Tests for scripts/install/pull-model.sh

setup() {
    # Use mktemp to ensure temp dir exists and is writable
    TEST_TMPDIR=$(mktemp -d)
    export OPENJARVIS_HOME="$TEST_TMPDIR/.openjarvis"
    mkdir -p "$OPENJARVIS_HOME/.state/models"
    export OLLAMA_STUB_LOG="$TEST_TMPDIR/ollama.log"
    : > "$OLLAMA_STUB_LOG"
    export PATH="$BATS_TEST_DIRNAME/stubs:$PATH"
    export SCRIPT="$BATS_TEST_DIRNAME/../../../scripts/install/pull-model.sh"
}

teardown() {
    # Clean up temp directory
    [[ -n "${TEST_TMPDIR:-}" ]] && rm -rf "$TEST_TMPDIR"
}

@test "writes .downloading marker, then .ready on success" {
    OLLAMA_STUB_EXIT=0 run bash "$SCRIPT" qwen3.5:2b
    [ "$status" -eq 0 ]
    [ -f "$OPENJARVIS_HOME/.state/models/qwen3.5:2b.ready" ]
    [ ! -f "$OPENJARVIS_HOME/.state/models/qwen3.5:2b.downloading" ]
}

@test "writes .failed on error after retries exhausted" {
    OLLAMA_STUB_EXIT=1 run bash "$SCRIPT" qwen3.5:2b
    [ "$status" -ne 0 ]
    [ -f "$OPENJARVIS_HOME/.state/models/qwen3.5:2b.failed" ]
}

@test "calls ollama pull with the right model name" {
    OLLAMA_STUB_EXIT=0 run bash "$SCRIPT" qwen3.5:9b
    grep -q "pull qwen3.5:9b" "$OLLAMA_STUB_LOG"
}

@test "retries 3 times on failure" {
    OLLAMA_STUB_EXIT=1 run bash "$SCRIPT" qwen3.5:2b
    pull_count=$(grep -c "pull qwen3.5:2b" "$OLLAMA_STUB_LOG")
    [ "$pull_count" -eq 3 ]
}

@test "ready marker is created via atomic rename (no .tmp leftovers)" {
    OLLAMA_STUB_EXIT=0 run bash "$SCRIPT" qwen3.5:2b
    leftover=$(find "$OPENJARVIS_HOME/.state/models" -name "*.tmp" 2>/dev/null | wc -l)
    [ "$leftover" -eq 0 ]
}
