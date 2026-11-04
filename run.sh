#!/usr/bin/env bash
# Forge Agent — one-command run (web UI)
set -e
cd "$(dirname "$0")"

if ! python3 -c "import fastapi, uvicorn, httpx, rich" 2>/dev/null; then
  echo "==> Cài dependencies Python..."
  pip3 install -q -r requirements.txt
fi

if [ ! -f server/static/index.html ]; then
  echo "==> Build web UI..."
  (cd web && npm install --no-audit --no-fund && npm run build)
fi

echo "==> Forge Agent chạy tại http://localhost:8000"
exec python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000
