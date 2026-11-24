#!/bin/sh
# Launch the OpenJarvis iPadOS HTTP Bridge Server in a-Shell.

set -e

IOS_DIR="${JARVIS_IOS_DIR:-$HOME/Documents/.jarvis/ios}"
export OPENJARVIS_CONFIG="${OPENJARVIS_CONFIG:-$HOME/Library/openjarvis/config.toml}"

echo "Starting OpenJarvis iPadOS bridge at http://127.0.0.1:8085 ..."
echo "Config: $OPENJARVIS_CONFIG"

exec python3 "$IOS_DIR/jarvis_server.py"
