#!/usr/bin/env bash
# forge-agent launcher (macOS/Linux) — logic chung nằm ở scripts/launch.py
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/launch.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python scripts/launch.py "$@"
else
  echo "[forge-agent] Không tìm thấy Python 3 — cài từ https://www.python.org/downloads/"
  exit 1
fi
