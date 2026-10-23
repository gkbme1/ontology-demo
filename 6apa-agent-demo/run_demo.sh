#!/usr/bin/env bash
# 一键起本体服务(8700) + 模拟 DCS(8900) + Agent 服务(8800) + 零依赖演示页(8081)。
# 本体服务目录通过 ONTOLOGY_HOME 指定，默认 ../6apa-ontology-demo。
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
ONTOLOGY_HOME="${ONTOLOGY_HOME:-$ROOT/../6apa-ontology-demo}"

cleanup() { kill $(jobs -p) 2>/dev/null || true; }
trap cleanup EXIT

if [ -d "$ONTOLOGY_HOME" ]; then
  echo "[1/4] 本体服务 :8700  ($ONTOLOGY_HOME)"
  (cd "$ONTOLOGY_HOME" && python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8700) &
  sleep 4
else
  echo "[1/4] 跳过本体服务：未找到 $ONTOLOGY_HOME（用 ONTOLOGY_HOME=路径 指定，或自行启动后设置 ONTOLOGY_BASE_URL）"
fi

echo "[2/4] 模拟 DCS 数据服务 :8900（实时值/历史值，模拟数据）"
./run_mock_dcs.sh &
sleep 3

echo "[3/4] Agent 服务 :8800"
./run_backend.sh &
sleep 4

echo "[4/4] 演示页 :8081  →  http://localhost:8081/index.html?api=http://localhost:8800"
(cd demo && python3 -m http.server 8081 --bind 127.0.0.1) &

wait
