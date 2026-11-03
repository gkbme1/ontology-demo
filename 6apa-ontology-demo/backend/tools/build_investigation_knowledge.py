"""生成调查知识表 data/source/6APA_调查知识.xlsx（原因分类、原因权重、化验项目、判定规则、漂移口径）。

    python3 -m backend.tools.build_investigation_knowledge          # 生成（已存在时不覆盖）
    python3 -m backend.tools.build_investigation_knowledge --force  # 覆盖为预填版

依据：需求梳理 BF-04（人机料法环）、BF-05（在线与化验 pH 差值恒定或扩大判异常）、UR-01（限值内缓慢漂移）、
UR-10（原因可设权重，车间主任提出）。全部标「草案·待工艺确认」，阈值与权重需现场标定。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.services import investigation as inv  # noqa: E402

OUT_FILE = ROOT / "data" / "source" / inv.KNOWLEDGE_FILE_NAME
STATUS = "草案·待工艺确认"
GROUP = "水解反应釜组(水解罐A–K)"

CATEGORIES = [
    ("人", "人员操作", "人为修改设定值、手动操作偏离规程、交接班遗漏", "", "操作、人为、手动、设定值修改、交接班", 1.0,
     "夜班人为上调温度设定值"),
    ("机", "设备与仪表", "设备、执行机构、仪表的故障或测量偏差", "执行机构、控制仪表、设备部件、生产设备、设备实例",
     "阀、泵、电极、搅拌、仪表、传感器、变送器、筛网", 1.0, "热水阀卡涩、pH 电极漂移、搅拌故障"),
    ("料", "物料", "来料、辅料与酶的状态", "物料流股", "进料、来料、浓度、原料、底物、RB、硼酸、氨水、酶", 1.0,
     "RB 液来料 pH / 浓度异常、氨水计量罐空罐、酶活衰减"),
    ("法", "方法与规程", "工艺参数设定、限值、控制程序与规程", "控制系统", "设定、限值、程序、SFC、规程、终点", 1.0,
     "限值设置不当、SFC 程序异常"),
    ("环", "环境与公用工程", "热水、蒸汽、压缩空气、冷盐水等公用工程与季节环境", "公用介质",
     "热水、蒸汽、压缩空气、仪表气、冷盐水、冷却水、环境、季节、气温", 1.0, "热水温度波动、压缩空气压力低、季节温差"),
]

WEIGHTS = [
    ("水解反应釜组(水解罐A–K)·双pH电极", "机", 1.3, "pH 传感器可能不准或滞后，是 pH 异常的首要排查点（10.16 力兴业）"),
    ("热水阀HV_1301", "机", 1.2, "热水阀卡涩会直接造成罐温偏离"),
    ("固定化酶活力稳定性", "料", 1.2, "换酶后批次越多酶活越低，反应变慢（10.19 力兴业）"),
    ("人为修改设定值", "人", 1.0, "异常调查精确到班次，结合操作记录定位人为原因（10.22 王金东）"),
    ("水解热水罐温度", "环", 0.9, "公用工程波动通常同时影响多台罐，单罐异常时降权"),
]

LAB_ITEMS = [
    ("PH", "水解液pH", "反应体系pH", GROUP, "水解罐{x}取样口", "反应中、终点", "pH", "AT_1301{x}1",
     "取样时刻前后在线均值", 2, "LIMS、人工录入",
     "化验与 DCS 存在时间差：按取样时间（不是报告时间）对齐；化验员只录一遍，调查与台账共用"),
    ("ZHL", "酶解转化率", "水解酶解转化率", GROUP, "水解罐{x}取样口", "终点", "%", "", "按批次对应", "", "LIMS",
     "批次结果指标，用于收率异常调查"),
]

RULES = [
    ("J-S11-01", "在线与化验 pH 偏差", "反应体系pH", GROUP, "AT_1301{x}1", "化验:PH", "差值恒定或扩大", 0.10, 0.02, 4,
     "反应、终点判定", "机", "BF-05：在线与化验的差异恒定或变大时，判定此处异常（10.16 力兴业）"),
    ("J-S11-02", "双电极偏差", "反应体系pH", GROUP, "AT_1301{x}1", "AT_1301{x}2", "差值恒定或扩大", 0.08, 0.02, 6,
     "反应", "机", "两支电极读数应一致；差值持续或扩大说明至少一支漂移（规则 R-S11-03）"),
]

DRIFT = [
    ("D-01", "默认", "CUSUM", "时间窗前 25% 为基线", "k=0.5；h=5",
     "按基线均值与标准差标准化后做双侧累积和，超过 h 判为持续偏移；对缓慢、持续的偏离比越限判断敏感"),
    ("D-02", "默认", "斜率", "时间窗前 25% 为基线", "sigma=3",
     "整窗线性趋势的总变化量 ≥ 3 倍基线波动，判为单向漂移"),
    ("D-03", "默认", "批间均值", "同一罐最近若干批的同一阶段", "batches=8；ratio=0.15",
     "逐批取同阶段均值，按中位数斜率（Theil–Sen，不受个别批次人为改设定值影响）估计趋势，"
     "总变化 ≥ 正常区间宽度的 15%（无限值时 ≥ 3 倍批间波动）判为批间漂移（温水煮青蛙）"),
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
    tables = [
        (inv.SHEET_CATEGORIES, inv.CATEGORY_COLUMNS, [(*r, STATUS) for r in CATEGORIES], [6, 14, 40, 40, 50, 9, 40, 14]),
        (inv.SHEET_WEIGHTS, inv.WEIGHT_COLUMNS, [(*r, "", STATUS) for r in WEIGHTS], [36, 6, 6, 60, 10, 14]),
        (inv.SHEET_LAB, inv.LAB_COLUMNS, [(*r, STATUS) for r in LAB_ITEMS], [8, 12, 14, 26, 16, 12, 6, 14, 18, 10, 14, 50, 14]),
        (inv.SHEET_RULES, inv.RULE_COLUMNS, [(*r, STATUS) for r in RULES], [9, 16, 12, 26, 14, 14, 14, 10, 10, 8, 14, 6, 50, 14]),
        (inv.SHEET_DRIFT, inv.DRIFT_COLUMNS, [(*r, STATUS) for r in DRIFT], [8, 8, 10, 26, 22, 60, 14]),
    ]
    with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as writer:
        for sheet, columns, rows, widths in tables:
            pd.DataFrame([dict(zip(columns, r)) for r in rows], columns=columns).to_excel(writer, sheet_name=sheet, index=False)
            _style(writer.sheets[sheet], widths)
    print(f"已生成 {OUT_FILE.relative_to(ROOT)}：原因分类 {len(CATEGORIES)}、原因权重 {len(WEIGHTS)}、化验项目 {len(LAB_ITEMS)}、"
          f"判定规则 {len(RULES)}、漂移口径 {len(DRIFT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
