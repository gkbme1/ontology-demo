#!/usr/bin/env bash
# 启动 Agent 服务。端口取自 .env 的 AGENT_PORT（默认 8800）。
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "未找到 .env，正在从 .env.example 复制……"
  cp .env.example .env
  echo "请编辑 .env 填入 LLM_API_KEY 后重新运行。"
  exit 1
fi

PORT="$(grep -E '^AGENT_PORT=' .env | cut -d= -f2 | tr -d '[:space:]')"
PORT="${PORT:-8800}"

echo "Agent 服务启动中：http://localhost:${PORT}"
exec python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}" "$@"
