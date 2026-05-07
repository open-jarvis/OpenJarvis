#!/usr/bin/env bash
#
# Download the Ollama binary for the target platform and place it
# in the Tauri binaries/ directory so it can be bundled as an
# externalBin sidecar.
#
# Usage:
#   ./download-ollama.sh                  # auto-detect current platform
#   ./download-ollama.sh aarch64-apple-darwin
#   ./download-ollama.sh x86_64-unknown-linux-gnu
#
# Ollama distributes platform binaries as archives (.tgz / .tar.zst).
# This script downloads, extracts the `ollama` CLI binary, renames it
# to the Tauri target-triple convention, and places it under
# frontend/src-tauri/binaries/.

set -euo pipefail

BINARIES_DIR="$(cd "$(dirname "$0")/../binaries" 2>/dev/null && pwd || echo "$(dirname "$0")/../binaries")"
mkdir -p "$BINARIES_DIR"

# Determine target triple
if [ "${1:-}" != "" ]; then
    TARGET="$1"
else
    ARCH="$(uname -m)"
    OS="$(uname -s)"
    case "$OS" in
        Darwin)
            case "$ARCH" in
                arm64)  TARGET="aarch64-apple-darwin" ;;
                x86_64) TARGET="x86_64-apple-darwin" ;;
                *)      echo "Unsupported arch: $ARCH"; exit 1 ;;
            esac
            ;;
        Linux)
            case "$ARCH" in
                x86_64)  TARGET="x86_64-unknown-linux-gnu" ;;
                aarch64) TARGET="aarch64-unknown-linux-gnu" ;;
                *)       echo "Unsupported arch: $ARCH"; exit 1 ;;
            esac
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT)
            TARGET="x86_64-pc-windows-msvc"
            ;;
        *)
            echo "Unsupported OS: $OS"; exit 1 ;;
    esac
fi

echo "Target triple: $TARGET"

# Tauri externalBin naming: <name>-<target-triple>[.exe]
SUFFIX=""
case "$TARGET" in
    *windows*) SUFFIX=".exe" ;;
esac
OUT_FILE="$BINARIES_DIR/ollama-${TARGET}${SUFFIX}"

if [ -f "$OUT_FILE" ]; then
    echo "Already exists: $OUT_FILE"
    echo "Delete it first to re-download."
    exit 0
fi

# Map target triple to Ollama release asset
RELEASE_URL="https://github.com/ollama/ollama/releases/latest/download"

case "$TARGET" in
    *apple-darwin)
        ASSET_URL="${RELEASE_URL}/ollama-darwin.tgz"
        ARCHIVE_TYPE="tgz"
        ;;
    x86_64-unknown-linux-gnu)
        ASSET_URL="${RELEASE_URL}/ollama-linux-amd64.tar.zst"
        ARCHIVE_TYPE="zst"
        ;;
    aarch64-unknown-linux-gnu)
        ASSET_URL="${RELEASE_URL}/ollama-linux-arm64.tar.zst"
        ARCHIVE_TYPE="zst"
        ;;
    x86_64-pc-windows-msvc)
        ASSET_URL="${RELEASE_URL}/ollama-windows-amd64.zip"
        ARCHIVE_TYPE="zip"
        ;;
    *)
        echo "No Ollama binary mapping for target: $TARGET"
        exit 1
        ;;
esac

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "Downloading: $ASSET_URL"
ARCHIVE_FILE="$TMPDIR/ollama-archive"
curl -fSL --progress-bar "$ASSET_URL" -o "$ARCHIVE_FILE"

echo "Extracting..."
case "$ARCHIVE_TYPE" in
    tgz)
        tar xzf "$ARCHIVE_FILE" -C "$TMPDIR"
        ;;
    zst)
        if command -v zstd &>/dev/null; then
            zstd -d "$ARCHIVE_FILE" -o "$TMPDIR/ollama.tar" --quiet
            tar xf "$TMPDIR/ollama.tar" -C "$TMPDIR"
        else
            echo "zstd not found. Install with: brew install zstd (macOS) or apt install zstd (Linux)"
            exit 1
        fi
        ;;
    zip)
        unzip -q "$ARCHIVE_FILE" -d "$TMPDIR"
        ;;
esac

# Find the ollama binary in the extracted contents
OLLAMA_BIN=""
for candidate in "$TMPDIR/bin/ollama" "$TMPDIR/ollama" "$TMPDIR/ollama.exe"; do
    if [ -f "$candidate" ]; then
        OLLAMA_BIN="$candidate"
        break
    fi
done

if [ -z "$OLLAMA_BIN" ]; then
    echo "Could not find ollama binary in archive. Contents:"
    find "$TMPDIR" -type f | head -20
    exit 1
fi

cp "$OLLAMA_BIN" "$OUT_FILE"
chmod +x "$OUT_FILE"

echo "Saved to: $OUT_FILE"
ls -lh "$OUT_FILE"
echo "Done."
