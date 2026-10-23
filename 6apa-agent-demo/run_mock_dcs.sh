#!/usr/bin/env bash
# 启动模拟 DCS 数据服务（实时值 / 历史值，返回的是模拟数据）。端口取 MOCK_DCS_PORT，默认 8900。
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m mock_dcs.main "$@"
