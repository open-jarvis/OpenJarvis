#!/usr/bin/env bats

setup() {
    TEST_TMPDIR=$(mktemp -d)
    export STUBS_DIR="$BATS_TEST_DIRNAME/stubs"
    export STUBS_NO_CARGO="$TEST_TMPDIR/stubs-no-cargo"
    mkdir -p "$STUBS_NO_CARGO"
    # Copy all stubs except cargo into the no-cargo dir.
    for s in "$STUBS_DIR"/*; do
        name=$(basename "$s")
        if [[ "$name" != "cargo" ]]; then
            cp "$s" "$STUBS_NO_CARGO/"
        fi
    done
    export RUSTUP_STUB_LOG="$TEST_TMPDIR/rustup.log"
    export CURL_STUB_LOG="$TEST_TMPDIR/curl.log"
    : > "$RUSTUP_STUB_LOG"
    : > "$CURL_STUB_LOG"
    export SCRIPT="$BATS_TEST_DIRNAME/../../../scripts/install/install-rust.sh"
}

teardown() {
    [[ -n "${TEST_TMPDIR:-}" ]] && rm -rf "$TEST_TMPDIR"
}

@test "skips install when cargo already present" {
    PATH="$STUBS_DIR:$PATH" run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    [ ! -s "$CURL_STUB_LOG" ]
}

@test "runs rustup curl-pipe-bash when cargo is missing" {
    PATH="$STUBS_NO_CARGO:/usr/bin:/bin:/usr/local/bin" run bash "$SCRIPT"
    grep -q "sh.rustup.rs" "$CURL_STUB_LOG"
}
