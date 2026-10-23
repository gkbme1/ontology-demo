#!/usr/bin/env bash
# 一键重建离线演示：解析 Excel → 导出 API 快照 → 组装 demo/index.html
set -euo pipefail
cd "$(dirname "$0")"
python3 -m backend.tools.build_mapping_template
python3 backend/tools/build_rule_template.py
python3 -m backend.tools.build_static_demo_data
python3 -m backend.tools.build_static_demo
python3 -m backend.export_static
echo
echo "打开 demo/index.html 即可查看离线演示"
