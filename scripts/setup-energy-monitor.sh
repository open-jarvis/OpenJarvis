#!/usr/bin/env bash
# Install the energy-measurement backend for this machine.
#
# Referenced by `jarvis bench --setup-energy` (see cli/bench_cmd.py), which
# built a path to this script and offered to run it while the file did not
# exist -- the offer silently did nothing.
#
# Picks the right extra by platform:
#   Apple Silicon -> energy-apple  (zeus-apple-silicon, IOReport, no root)
#   Linux + NVIDIA -> gpu-metrics  (pynvml)
#   Linux + AMD    -> energy-amd   (amdsmi)
#   Linux, neither -> nothing to install; RAPL is read from sysfs
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is required. See https://docs.astral.sh/uv/" >&2
    exit 1
fi

os="$(uname -s)"
arch="$(uname -m)"

case "$os" in
Darwin)
    if [ "$arch" != "arm64" ]; then
        echo "Intel Macs expose no energy counters OpenJarvis can read." >&2
        exit 1
    fi
    extra="energy-apple"
    ;;
Linux)
    if command -v nvidia-smi >/dev/null 2>&1; then
        extra="gpu-metrics"
    elif command -v rocm-smi >/dev/null 2>&1; then
        extra="energy-amd"
    elif [ -d /sys/class/powercap/intel-rapl ]; then
        echo "RAPL is readable from sysfs; no extra package needed."
        echo "If readings come back empty, check permissions on"
        echo "  /sys/class/powercap/intel-rapl/*/energy_uj"
        exit 0
    else
        echo "No supported energy backend detected on this host." >&2
        exit 1
    fi
    ;;
*)
    echo "Energy measurement is not supported on $os." >&2
    exit 1
    ;;
esac

echo "Installing openjarvis[$extra] ..."
# --inexact: add this extra without pruning extras the user already has.
# A plain `uv sync --extra` would uninstall e.g. [dev] and [server].
uv sync --inexact --extra "$extra"

echo
echo "Verifying ..."
uv run python - <<'PY'
from openjarvis.telemetry.energy_monitor import create_energy_monitor

monitor = create_energy_monitor()
if monitor is None:
    raise SystemExit(
        "Energy monitor still unavailable. Run `jarvis doctor` for details."
    )
print(f"OK: {monitor.vendor().value} via {monitor.energy_method()}")
monitor.close()
PY
