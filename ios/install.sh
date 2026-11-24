#!/bin/sh
# One-liner setup script for OpenJarvis on iPadOS (a-Shell / a-Shell mini).

set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
IOS_DEST="$HOME/Documents/.jarvis/ios"
CFG_DIR="$HOME/Library/openjarvis"
CFG_DEST="$CFG_DIR/config.toml"
PROFILE="$HOME/.profile"

mkdir -p "$IOS_DEST" "$CFG_DIR"

cp "$SCRIPT_DIR/jarvis_ios.py" "$IOS_DEST/jarvis_ios.py"
cp "$SCRIPT_DIR/jarvis_server.py" "$IOS_DEST/jarvis_server.py"
cp "$SCRIPT_DIR/start_jarvis.sh" "$IOS_DEST/start_jarvis.sh"
chmod +x "$IOS_DEST/start_jarvis.sh"

if [ ! -f "$CFG_DEST" ]; then
  cp "$SCRIPT_DIR/config.toml" "$CFG_DEST"
  echo "Created $CFG_DEST"
else
  echo "Preserving existing $CFG_DEST"
fi

echo "Installing OpenJarvis (pure-Python, --no-deps) from $REPO_ROOT ..."
pip install --no-deps -e "$REPO_ROOT"

if [ ! -f "$PROFILE" ] || ! grep -q "OPENJARVIS_CONFIG" "$PROFILE"; then
  {
    echo ""
    echo "# OpenJarvis iPadOS (a-Shell)"
    echo "export OPENJARVIS_CONFIG=\"$CFG_DEST\""
    echo "alias jarvis=\"python3 $IOS_DEST/jarvis_ios.py\""
    echo "alias start_jarvis=\"sh $IOS_DEST/start_jarvis.sh\""
  } >> "$PROFILE"
  echo "Updated $PROFILE with jarvis and start_jarvis aliases."
fi

echo "Done! Run 'source ~/.profile' then 'start_jarvis'."
