#!/usr/bin/env bash
# Quick scan for accidental secrets before git push.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAIL=0

_patterns() {
  rg -n --hidden \
    -g '!.git' \
    -g '!uv.lock' \
    -g '!**/package-lock.json' \
    -g '!**/Cargo.lock' \
    -g '!**/*.png' \
    -g '!**/*.jpg' \
    -g '!**/tests/**' \
    -g '!**/test_*.py' \
    -g '!scripts/check-no-secrets.sh' \
    -g '!docs/**' \
    -g '!examples/**' \
    -g '!frontend/**' \
    -g '!rust/**' \
    -g '!src/openjarvis/security/**' \
    -g '!src/openjarvis/cli/deep_research_setup_cmd.py' \
    -e "${1}" \
    . 2>/dev/null || true
}

echo "Checking for credential patterns..."
for pat in 'sk-[a-zA-Z0-9]{20,}' 'ghp_[a-zA-Z0-9]{36}' 'xoxb-' 'GITHUB_PERSONAL_ACCESS_TOKEN\s*=\s*["\x27][a-zA-Z0-9]' '/home/dozey' '/home/Dozey'; do
  hits=$(_patterns "$pat" | head -5)
  if [[ -n "$hits" ]]; then
    echo "WARN pattern $pat:"
    echo "$hits"
    FAIL=1
  fi
done

if git ls-files '*.env' '*.env.*' 2>/dev/null | grep -q .; then
  echo "FAIL: .env files are tracked by git"
  git ls-files '*.env' '*.env.*'
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "OK: no obvious secret patterns in tracked tree (review WARN paths manually)."
  exit 0
fi
echo "Review warnings above before pushing."
exit 1
