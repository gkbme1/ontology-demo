"""生成限值版本表 data/source/6APA_限值版本.xlsx（条件化限值与修改记录的预填示例）。

    python3 -m backend.tools.build_limit_versions          # 生成（已存在时不覆盖：在线修改都追加在这张表里）
    python3 -m backend.tools.build_limit_versions --force  # 覆盖为预填版（会丢掉在线修改的版本）

预填三条示例，均为「草案·待工艺确认」：
- PL001 釜内反应温度：换酶后 801 批以上正常区间上移（BF-07「批次越多设定越高」）；
- PL002 反应体系pH：换酶后 801 批以上同理；
- PL002 反应体系pH：换酶后 1～800 批按「模型最优值 ± 差值」（BF-12；底物预测模型未接入，最优值为示例）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.services import limit_versions as lv  # noqa: E402

STATUS = "草案·待工艺确认"
ROWS = [
    # 版本, 限值, 设备, 换酶下限, 上限, LL, L, NL, NH, H, HH, 来源, 最优, 差值, 生效, 失效, 状态, 修改人, 原因, 记录
    ("PL001-V1", "PL001", "", 801, None, 30.5, 32.5, 33.5, 35.5, 36.0, 37.5, "人工设定", None, None,
     "2026-09-01 00:00:00", None, STATUS, "工艺员（示例）", "换酶后批次越多，温度设定越高（BF-07，10.19 力兴业）", "2026-09-01 08:30:00"),
    ("PL002-V1", "PL002", "", 801, None, 7.1, 7.6, 7.9, 8.3, 8.5, 8.9, "人工设定", None, None,
     "2026-09-01 00:00:00", None, STATUS, "工艺员（示例）", "换酶后批次越多，pH 设定越高（BF-07）", "2026-09-01 08:30:00"),
    ("PL002-V2", "PL002", "", 1, 800, None, None, None, None, None, None, "模型最优值±差值", 7.95, 0.2,
     "2026-10-20 00:00:00", None, STATUS, "底物预测模型（示例）",
     "按最优值 ± 差值生成正常区间（BF-12）；模型未接入，最优值为示例", "2026-10-20 08:00:00"),
]


def main() -> int:
    out = lv.VERSION_FILE
    if out.exists() and "--force" not in sys.argv:
        print(f"{out.name} 已存在，未覆盖（在线修改的版本都在这张表里；覆盖为预填版请加 --force）")
        return 0
    wb = Workbook()
    ws = wb.active
    ws.title = lv.SHEET
    ws.append(lv.COLUMNS)
    for row in ROWS:
        ws.append(list(row))
    for i, w in enumerate([10, 8, 10, 10, 10, 8, 8, 8, 8, 8, 8, 16, 7, 6, 20, 20, 14, 18, 50, 20], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
    ws.freeze_panes = "C2"
    wb.save(out)
    print(f"已生成 {out.relative_to(ROOT)}：{len(ROWS)} 个示例版本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
