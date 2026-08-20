#!/usr/bin/env bash
set -euo pipefail

# Bump the desktop app version across all 3 config files.
# Usage: ./scripts/bump-desktop-version.sh <semver>
# Example: ./scripts/bump-desktop-version.sh 1.0.1

if [ $# -ne 1 ]; then
  echo "Usage: $0 <version>"
  echo "Example: $0 1.0.1"
  exit 1
fi

VERSION="$1"

# Validate semver (major.minor.patch, optional pre-release)
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
  echo "Error: '$VERSION' is not a valid semver (expected X.Y.Z or X.Y.Z-pre)"
  exit 1
fi

FRONTEND_DIR="$(cd "$(dirname "$0")/../frontend" && pwd)"

# 1. package.json
node -e "
  const fs = require('fs');
  const path = '${FRONTEND_DIR}/package.json';
  const pkg = JSON.parse(fs.readFileSync(path, 'utf8'));
  pkg.version = '${VERSION}';
  fs.writeFileSync(path, JSON.stringify(pkg, null, 2) + '\n');
"
echo "Updated frontend/package.json -> ${VERSION}"

# 2. tauri.conf.json
node -e "
  const fs = require('fs');
  const path = '${FRONTEND_DIR}/src-tauri/tauri.conf.json';
  const conf = JSON.parse(fs.readFileSync(path, 'utf8'));
  conf.version = '${VERSION}';
  fs.writeFileSync(path, JSON.stringify(conf, null, 2) + '\n');
"
echo "Updated frontend/src-tauri/tauri.conf.json -> ${VERSION}"

# 3. Cargo.toml
sed -i.bak "s/^version = \".*\"/version = \"${VERSION}\"/" "${FRONTEND_DIR}/src-tauri/Cargo.toml"
rm -f "${FRONTEND_DIR}/src-tauri/Cargo.toml.bak"
echo "Updated frontend/src-tauri/Cargo.toml -> ${VERSION}"

echo ""
echo "Version bumped to ${VERSION} in all 3 files."
echo ""
echo "Next steps:"
echo "  git add frontend/package.json frontend/src-tauri/tauri.conf.json frontend/src-tauri/Cargo.toml"
echo "  git commit -m \"chore(desktop): bump version to ${VERSION}\""
echo "  git tag desktop-v${VERSION}"
echo "  git push origin main --tags"
