"""生成工序与工艺阶段定义表 data/source/6APA_工序与阶段.xlsx。

    python3 -m backend.tools.build_process_steps          # 生成（已存在时不覆盖）
    python3 -m backend.tools.build_process_steps --force  # 覆盖为预填版

- 「工序」：105 车间八道工序（提取、水洗、脱色、抽取、水解、萃取、薄膜、结晶，按调研顺序）与工段的对应；
- 「工艺阶段」：工序内的阶段、阶段识别依据（EBR 阶段名，或 DCS 位号条件）、对应的工艺限值操作模式。
  目前只有水解工序定义了阶段（进料 / 反应 / 终点判定 / 出料 / 空闲），其余工序待现场补充；
- 「运行上下文」：罐批次、换酶后批次计数、班次从哪个系统来、经哪个本体能力取。
全部标「草案·待工艺确认」。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.services import process_context as pc  # noqa: E402

OUT_FILE = ROOT / "data" / "source" / pc.PROCESS_FILE_NAME
STATUS = "草案·待工艺确认"

STEPS = [
    ("P01", "提取", 1, "S01", "S02、S03、S04", "RSE300 一 / 二萃提取；辅料：三萃及溶媒周转、稀硫酸、破乳剂"),
    ("P02", "水洗", 2, "S05", "", "BA 水洗"),
    ("P03", "脱色", 3, "S06", "", "活性炭脱色与芬特过滤"),
    ("P04", "抽取", 4, "S07", "", "6APA 抽提（碳酸钾反萃）"),
    ("P05", "水解", 5, "S11", "S10", "酶法水解；辅料：水解辅料配制（硼酸、氨水）"),
    ("P06", "萃取", 6, "S12", "", "萃取与反萃（苯乙酸分离）"),
    ("P07", "薄膜", 7, "S09", "", "薄膜蒸发（RB 脱溶）；工艺流向上位于水解之前"),
    ("P08", "结晶", 8, "S13", "S14、S15", "6APA 批次结晶与离心；辅料：连续结晶、结晶辅料储运"),
]

# 阶段识别：DCS 条件写成「位号模板=值」，多个条件用「；」连接表示同时满足，{x} 为罐号
STAGES = [
    ("P05", "S-01", "进料", 1, "水解反应釜组(水解罐A–K)", "进料", "XV_1302{x}_VAL2=1", "进料过程",
     "RB 进料阀开；硼酸同期进料"),
    ("P05", "S-02", "反应", 2, "水解反应釜组(水解罐A–K)", "反应", "P_1303{x}_RUN=1；XV_1304{x}_VAL2=1", "水解反应期",
     "搅拌运行且氨水进料阀开（按 pH 滴加氨水）"),
    ("P05", "S-03", "终点判定", 3, "水解反应釜组(水解罐A–K)", "终点判定", "P_1303{x}_RUN=1；XV_1304{x}_VAL2=0", "水解反应期",
     "搅拌运行、氨水进料阀关（氨耗趋零，见 R-S11-05）"),
    ("P05", "S-04", "出料", 4, "水解反应釜组(水解罐A–K)", "出料", "XV_1308{x}_FT=1", "出料过程",
     "压缩空气压料，出料流量检测有信号"),
    ("P05", "S-05", "空闲", 5, "水解反应釜组(水解罐A–K)", "空闲", "", "",
     "以上条件都不满足"),
]

CONTEXTS = [
    ("罐批次", "水解", "水解反应釜组(水解罐A–K)", "EBR", "CAP-007", "批号、批次起止、反应起止、各阶段起止",
     "调查时间窗以罐批次的反应起止为准（10.15 王金东）；EBR 未就绪时按「工艺阶段」的 DCS 条件推断"),
    ("换酶后批次计数", "水解", "水解反应釜组(水解罐A–K)", "EBR", "CAP-007", "enzymeBatchCount、酶批号",
     "酶活无法在线检测，以换酶后批次数作替代指标；一般 1000 批以上换酶（10.19 力兴业）"),
    ("班次", "全部", "", "MOM worktrans", "CAP-008", "日期、班次、班组、起止时间",
     "异常调查精确到班次，结合操作记录定位人为原因（10.22 王金东）"),
]


def _style(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "B2"


def main() -> int:
    if OUT_FILE.exists() and "--force" not in sys.argv:
        print(f"{OUT_FILE.name} 已存在，未覆盖（覆盖为预填版请加 --force）")
        return 0
    steps = [dict(zip(pc.STEP_COLUMNS, (*row, STATUS))) for row in STEPS]
    stages = [dict(zip(pc.STAGE_COLUMNS, (*row, STATUS))) for row in STAGES]
    contexts = [dict(zip(pc.CONTEXT_COLUMNS, (*row, STATUS))) for row in CONTEXTS]
    with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as writer:
        pd.DataFrame(steps, columns=pc.STEP_COLUMNS).to_excel(writer, sheet_name=pc.SHEET_STEPS, index=False)
        pd.DataFrame(stages, columns=pc.STAGE_COLUMNS).to_excel(writer, sheet_name=pc.SHEET_STAGES, index=False)
        pd.DataFrame(contexts, columns=pc.CONTEXT_COLUMNS).to_excel(writer, sheet_name=pc.SHEET_CONTEXTS, index=False)
        _style(writer.sheets[pc.SHEET_STEPS], [8, 8, 6, 10, 16, 50, 14])
        _style(writer.sheets[pc.SHEET_STAGES], [8, 8, 10, 6, 26, 10, 36, 14, 40, 14])
        _style(writer.sheets[pc.SHEET_CONTEXTS], [14, 8, 26, 14, 9, 36, 60, 14])
    print(f"已生成 {OUT_FILE.relative_to(ROOT)}：{len(steps)} 道工序，{len(stages)} 个工艺阶段（水解），{len(contexts)} 类运行上下文")
    return 0


if __name__ == "__main__":
    sys.exit(main())
