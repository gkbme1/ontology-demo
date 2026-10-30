#!/usr/bin/env bash
# 启动本体前端（Vite 开发服务器，默认 5173；/api 代理到本体服务 8700，见 frontend/.env）。需要 Node.js 18+。
set -euo pipefail
cd "$(dirname "$0")/frontend"
command -v npm >/dev/null || { echo "未找到 npm：请先安装 Node.js 18+"; exit 1; }
if [ ! -x node_modules/.bin/vite ]; then
  echo "首次运行，安装前端依赖……（package-lock.json 使用 npmmirror 镜像，不通时加 --registry=https://registry.npmjs.org/）"
  npm install --no-audit --no-fund
fi
echo "本体前端：http://localhost:5173"
exec npm run dev -- --host 127.0.0.1
