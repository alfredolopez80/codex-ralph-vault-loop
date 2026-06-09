#!/usr/bin/env bash
set -euo pipefail

if command -v semgrep > /dev/null 2>&1 && semgrep --version > /dev/null 2>&1; then
  exec semgrep scan --quiet --error --config .semgrep.yml "$@"
fi

if command -v sfw > /dev/null 2>&1; then
  exec sfw uvx semgrep==1.165.0 scan --quiet --error --config .semgrep.yml "$@"
fi

cat >&2 << 'EOF'
semgrep-local-scan requires a working semgrep binary.
Install semgrep locally, or install sfw so the hook can run the pinned fallback:
sfw uvx semgrep==1.165.0
EOF
exit 127
