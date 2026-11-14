#!/usr/bin/env bash
# 一键启动 6APA 本体 Demo v2。
#   ./run_demo.sh         构建前端（如未构建）并启动后端，浏览器打开 http://localhost:8710/
#   ./run_demo.sh dev     后端 8710 + vite 开发服务器 5180（改前端代码时用）
set -euo pipefail
cd "$(dirname "$0")"
PORT="${V2_PORT:-8710}"

python3 -c "import fastapi, uvicorn, pandas, openpyxl, numpy" 2>/dev/null || pip install -r requirements.txt
[ -f data/config/6APA_空间层级.xlsx ] || python3 -m backend.tools.build_config
[ -f data/seed/phenomena.json ] || python3 -m backend.tools.build_seed

if [ "${1:-}" = "dev" ]; then
  (cd frontend && [ -d node_modules ] || npm install)
  V2_PORT="$PORT" python3 -m backend.main &
  BACK=$!
  trap 'kill $BACK 2>/dev/null' EXIT
  cd frontend && npx vite
else
  if [ ! -f frontend/dist/index.html ]; then
    (cd frontend && { [ -d node_modules ] || npm install; } && npm run build)
  fi
  echo "打开 http://localhost:${PORT}/"
  V2_PORT="$PORT" exec python3 -m backend.main
fi
