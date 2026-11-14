#!/usr/bin/env bash
# ALIBI: one command to launch the case board (API + built UI) on localhost.
#   ./start.sh            build the UI if needed, then serve on http://127.0.0.1:8000
#   ./start.sh --port N   use another port
#   ./start.sh --rebuild  force a UI rebuild first
# Stop with Ctrl-C. Runs fully offline by default (RUNTIME_MODE=offline, zero model calls).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${ALIBI_PORT:-8000}"
REBUILD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --rebuild) REBUILD=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  echo "error: 'uv' is not installed. See https://docs.astral.sh/uv/ then run: uv sync" >&2; exit 1
fi

needs_build=0
[ -f web/dist/index.html ] || needs_build=1
if [ "$needs_build" -eq 0 ] && [ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html 2>/dev/null | head -1)" ]; then
  needs_build=1
fi
if [ "$REBUILD" -eq 1 ] || [ "$needs_build" -eq 1 ]; then
  if ! command -v npm >/dev/null 2>&1; then
    if [ -f web/dist/index.html ]; then
      echo "warning: npm not found; serving the existing (possibly stale) UI build." >&2
    else
      echo "error: the UI is not built and 'npm' is not installed. Install Node 20+ and rerun ./start.sh" >&2; exit 1
    fi
  else
    echo "Building the case board UI ..."
    [ -d web/node_modules ] || npm --prefix web ci --no-audit --no-fund
    npm --prefix web run build
  fi
fi

echo "Starting ALIBI on http://127.0.0.1:${PORT}  (Ctrl-C to stop)"
exec uv run alibi serve --port "${PORT}"
