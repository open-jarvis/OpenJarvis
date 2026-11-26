#!/usr/bin/env bash
#
# Download the Ollama binary for the target platform and place it
# in the Tauri binaries/ directory so it can be bundled as an
# externalBin sidecar.
#
# Usage:
#   ./download-ollama.sh                  # auto-detect current platform
#   ./download-ollama.sh aarch64-apple-darwin
#   ./download-ollama.sh universal-apple-darwin
#   ./download-ollama.sh x86_64-unknown-linux-gnu
#   ./download-ollama.sh aarch64-pc-windows-msvc
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
            # Git Bash can report x86_64 when running under emulation on ARM.
            case "${PROCESSOR_ARCHITEW6432:-${PROCESSOR_ARCHITECTURE:-$ARCH}}" in
                ARM64|arm64|aarch64) TARGET="aarch64-pc-windows-msvc" ;;
                AMD64|amd64|x86_64) TARGET="x86_64-pc-windows-msvc" ;;
                *) echo "Unsupported Windows arch: $ARCH"; exit 1 ;;
            esac
            ;;
        *)
            echo "Unsupported OS: $OS"; exit 1 ;;
    esac
fi

echo "Target triple: $TARGET"

# Pin the upstream release and verify the archive before extracting it. When
# bumping, update OLLAMA_VERSION and every digest from that release's
# sha256sum.txt.
OLLAMA_VERSION="v0.40.18"
RELEASE_URL="https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}"
# Space-separated archive paths left out of the Windows runtime stage.
RUNTIME_EXCLUDES=""

case "$TARGET" in
    *apple-darwin)
        ASSET="ollama-darwin.tgz"
        ASSET_SHA256="015261f434d31d7f0781f8ba6b59cc8e1f70ecb562a4e6db44dfdd5e02f7e562"
        ARCHIVE_TYPE="tgz"
        ;;
    x86_64-unknown-linux-gnu)
        ASSET="ollama-linux-amd64.tar.zst"
        ASSET_SHA256="b82649006cb5b54ed1237fa2d1a26a7f939a4fd03150033759acbff7ff315adf"
        ARCHIVE_TYPE="zst"
        ;;
    aarch64-unknown-linux-gnu)
        ASSET="ollama-linux-arm64.tar.zst"
        ASSET_SHA256="63f01dae3b65641866991e75e2aecb7aed8a4041f4c2c3c7d92862c5a47ebed6"
        ARCHIVE_TYPE="zst"
        ;;
    x86_64-pc-windows-msvc)
        ASSET="ollama-windows-amd64.zip"
        ASSET_SHA256="ca97292ac1e9acc77fcf473bb2741fa6acd12e3798f261b419680068b7cc4c16"
        ARCHIVE_TYPE="zip"
        # The full x64 runtime (~2.2 GB) exceeds the ~2 GB payload limit of
        # both NSIS and MSI. CUDA v12 covers the widest range of NVIDIA GPUs
        # and drivers; others fall back to the Vulkan and CPU runners.
        RUNTIME_EXCLUDES="lib/ollama/cuda_v13"
        ;;
    aarch64-pc-windows-msvc)
        ASSET="ollama-windows-arm64.zip"
        ASSET_SHA256="671d27e9f93e14662f3941d705e4b3626fc05bd120055f160489c80c9c552912"
        ARCHIVE_TYPE="zip"
        ;;
    *)
        echo "No Ollama binary mapping for target: $TARGET"
        exit 1
        ;;
esac
ASSET_URL="${RELEASE_URL}/${ASSET}"

# Tauri externalBin naming: <name>-<target-triple>[.exe]
SUFFIX=""
case "$TARGET" in
    *windows*) SUFFIX=".exe" ;;
esac
OUT_FILE="$BINARIES_DIR/ollama-${TARGET}${SUFFIX}"
RUNTIME_DIR="$BINARIES_DIR/ollama-runtime-${TARGET}"
# Written last, so it only exists once the sidecar and runtime are complete.
MANIFEST="$BINARIES_DIR/ollama-runtime-${TARGET}.manifest"
# Windows inference needs the archive's DLLs and this lib/ollama runner.
WINDOWS_RUNNER="lib/ollama/llama-server.exe"

is_windows_target() {
    [[ "$TARGET" == *windows* ]]
}

sha256_of() {
    if command -v sha256sum &>/dev/null; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

# List "<size> <relative path>" for every file under $1, in a stable order.
list_runtime_files() {
    (cd "$1" && find . -type f -print | LC_ALL=C sort | while IFS= read -r file; do
        printf '%s %s\n' "$(wc -c < "$file" | tr -d ' ')" "${file#./}"
    done)
}

# A Windows stage is reusable only if it came from the pinned archive and
# every file recorded at publish time is still present with the same size.
runtime_stage_is_complete() {
    [ -f "$OUT_FILE" ] && [ -f "$MANIFEST" ] || return 1
    [ "$(sed -n 1p "$MANIFEST")" = "archive $ASSET_SHA256 excluding ${RUNTIME_EXCLUDES:-nothing}" ] || return 1
    [ "$(sed -n 2p "$MANIFEST")" = "sidecar $(sha256_of "$OUT_FILE")" ] || return 1
    [ -f "$RUNTIME_DIR/$WINDOWS_RUNNER" ] || return 1
    [ "$(tail -n +3 "$MANIFEST")" = "$(list_runtime_files "$RUNTIME_DIR")" ]
}

if is_windows_target; then
    if runtime_stage_is_complete; then
        echo "Already staged: $OUT_FILE and $RUNTIME_DIR ($OLLAMA_VERSION)"
        exit 0
    fi
    if [ -e "$OUT_FILE" ] || [ -e "$RUNTIME_DIR" ]; then
        echo "Existing Windows Ollama stage is incomplete or stale; restaging."
    fi
elif [ -f "$OUT_FILE" ]; then
    echo "Already exists: $OUT_FILE"
    echo "Delete it first to re-download."
    exit 0
fi

# Stage beside the destination so publishing is a rename, not a second copy.
OLLAMA_TMP_DIR="$(mktemp -d "$BINARIES_DIR/ollama-download.XXXXXX")"
trap 'rm -rf "$OLLAMA_TMP_DIR"' EXIT

echo "Downloading: $ASSET_URL"
ARCHIVE_FILE="$OLLAMA_TMP_DIR/ollama-archive"
curl -fSL --progress-bar "$ASSET_URL" -o "$ARCHIVE_FILE"

ACTUAL_SHA256="$(sha256_of "$ARCHIVE_FILE")"
if [ "$ACTUAL_SHA256" != "$ASSET_SHA256" ]; then
    echo "Checksum mismatch for $ASSET ($OLLAMA_VERSION)"
    echo "  expected: $ASSET_SHA256"
    echo "  actual:   $ACTUAL_SHA256"
    exit 1
fi

EXTRACT_DIR="$OLLAMA_TMP_DIR/extract"
mkdir -p "$EXTRACT_DIR"
echo "Extracting..."
case "$ARCHIVE_TYPE" in
    tgz)
        tar xzf "$ARCHIVE_FILE" -C "$EXTRACT_DIR"
        ;;
    zst)
        if command -v zstd &>/dev/null; then
            zstd -d "$ARCHIVE_FILE" -o "$OLLAMA_TMP_DIR/ollama.tar" --quiet
            tar xf "$OLLAMA_TMP_DIR/ollama.tar" -C "$EXTRACT_DIR"
        else
            echo "zstd not found. Install with: brew install zstd (macOS) or apt install zstd (Linux)"
            exit 1
        fi
        ;;
    zip)
        unzip -q "$ARCHIVE_FILE" -d "$EXTRACT_DIR"
        ;;
esac
rm -f "$ARCHIVE_FILE"

# Find the ollama binary in the extracted contents
OLLAMA_BIN=""
for candidate in "$EXTRACT_DIR/bin/ollama" "$EXTRACT_DIR/ollama" "$EXTRACT_DIR/ollama.exe"; do
    if [ -f "$candidate" ]; then
        OLLAMA_BIN="$candidate"
        break
    fi
done

if [ -z "$OLLAMA_BIN" ]; then
    echo "Could not find ollama binary in archive. Contents:"
    find "$EXTRACT_DIR" -type f | head -20
    exit 1
fi

# Tauri's universal macOS bundle needs both architectures in a single sidecar.
if [ "$TARGET" = "universal-apple-darwin" ]; then
    if ! lipo "$OLLAMA_BIN" -verify_arch arm64 x86_64; then
        echo "Ollama's darwin archive does not contain a universal arm64+x86_64 binary"
        exit 1
    fi
fi

if ! is_windows_target; then
    cp "$OLLAMA_BIN" "$OUT_FILE.partial"
    chmod +x "$OUT_FILE.partial"
    mv -f "$OUT_FILE.partial" "$OUT_FILE"
    echo "Saved to: $OUT_FILE"
    ls -lh "$OUT_FILE"
    echo "Done."
    exit 0
fi

if [ ! -f "$EXTRACT_DIR/$WINDOWS_RUNNER" ]; then
    echo "Windows Ollama archive is missing its lib/ollama inference runtime ($WINDOWS_RUNNER)"
    exit 1
fi

# Preserve the release layout beside the renamed sidecar; the release config
# maps this directory beside the installed ollama.exe. Assemble everything in
# the temporary stage first, then publish by rename.
SIDECAR_STAGE="$OLLAMA_TMP_DIR/sidecar$SUFFIX"
RUNTIME_STAGE="$OLLAMA_TMP_DIR/runtime"
mv "$OLLAMA_BIN" "$SIDECAR_STAGE"
chmod +x "$SIDECAR_STAGE"
mv "$EXTRACT_DIR" "$RUNTIME_STAGE"
[ -f "$RUNTIME_STAGE/$WINDOWS_RUNNER" ]
for excluded in $RUNTIME_EXCLUDES; do
    rm -rf "${RUNTIME_STAGE:?}/$excluded"
done

MANIFEST_STAGE="$OLLAMA_TMP_DIR/manifest"
{
    echo "archive $ASSET_SHA256 excluding ${RUNTIME_EXCLUDES:-nothing}"
    echo "sidecar $(sha256_of "$SIDECAR_STAGE")"
    list_runtime_files "$RUNTIME_STAGE"
} > "$MANIFEST_STAGE"

# Invalidate the old stage before touching it, so an interruption below is
# always detected and restaged on the next run.
rm -f "$MANIFEST"
rm -rf "$RUNTIME_DIR"
mv "$RUNTIME_STAGE" "$RUNTIME_DIR"
mv -f "$SIDECAR_STAGE" "$OUT_FILE"
mv "$MANIFEST_STAGE" "$MANIFEST"

echo "Saved to: $OUT_FILE"
echo "Runtime:  $RUNTIME_DIR ($(( $(wc -l < "$MANIFEST") - 2 )) files)"
ls -lh "$OUT_FILE"
echo "Done."
