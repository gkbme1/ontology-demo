#!/usr/bin/env bash
# 启动 Vue 前端开发服务器。首次运行会自动 npm install。
set -euo pipefail
cd "$(dirname "$0")/frontend"

[ -f .env ] || cp .env.example .env
[ -d node_modules ] || npm install

exec npm run dev
