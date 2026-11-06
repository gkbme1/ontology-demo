"""生成设备设计参数表 data/config/6APA_设备设计参数.xlsx（材质、容积、高度等固定参数）。

两张表：
- 参数模板：按设备类型给出应有的设计参数（参数名、单位、说明）。设备按「匹配关键字」命中第一个模板
  （先看设备名称，再看设备组声明的设备类型）；
- 参数值：按对象（设备或设备组名称）填写数值。设备组上填的值对组内每台生效，设备上填的值优先。

点表里没有铭牌数据，参数值表初始为空，界面显示「待补充」，由现场按设备档案 / 铭牌填写，不编造。
已存在时不覆盖，--force 才覆盖。

    python3 -m backend.tools.build_design_params [--force]
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "data" / "config" / "6APA_设备设计参数.xlsx"

COMMON_TANK = [
    ("设备位号", "", "设备铭牌 / 设备台账上的位号，如 R-1301A"),
    ("材质", "", "罐体材质，如 S30408 / S31603 / 碳钢衬胶"),
    ("设计容积", "m³", "全容积"),
    ("有效容积", "m³", "最大装料量对应容积"),
    ("内径", "mm", ""),
    ("筒体高度", "mm", "直筒段高度"),
    ("设计压力", "MPa", "罐内 / 夹套分别填写时用「罐内 / 夹套」"),
    ("设计温度", "℃", ""),
]
AGITATOR = [
    ("搅拌形式", "", "如 推进式 / 桨式 / 锚式"),
    ("搅拌电机功率", "kW", ""),
    ("搅拌转速", "rpm", ""),
]
MAKER = [("制造厂家", "", ""), ("投用日期", "", "")]

TEMPLATES = [
    # 模板名, 匹配关键字（、分隔，命中设备类型或名称）, 参数
    ("固定化酶反应罐", "固定化酶反应罐、水解罐", COMMON_TANK + [("换热形式", "", "如 夹套热水 / 盘管")] + AGITATOR +
     [("固定化酶装填量", "kg", "每罐装填量"), ("换酶周期", "批", "一般 1000 批以上需换酶（调研 BF-09），以现场为准")] + MAKER),
    ("搅拌罐", "搅拌、结晶罐、混合罐、配制罐、吸附罐", COMMON_TANK + [("换热形式", "", "")] + AGITATOR + MAKER),
    ("储罐 / 计量罐", "储罐、计量罐、缓冲罐、中和罐、分层罐、分相罐、罐", COMMON_TANK + MAKER),
    ("泵", "泵", [("型号", "", ""), ("过流部件材质", "", ""), ("额定流量", "m³/h", ""), ("扬程", "m", ""),
                 ("电机功率", "kW", ""), ("额定转速", "rpm", ""), ("是否变频", "", "是 / 否")] + MAKER),
    ("离心机", "离心机", [("型号", "", ""), ("转鼓材质", "", ""), ("处理能力", "m³/h", ""), ("转鼓直径", "mm", ""),
                         ("电机功率", "kW", ""), ("最高转速", "rpm", "")] + MAKER),
    ("换热器", "换热器、冷凝器", [("型号", "", ""), ("材质", "", ""), ("换热面积", "m²", ""), ("设计压力", "MPa", "管程 / 壳程"),
                              ("设计温度", "℃", "管程 / 壳程")] + MAKER),
    ("塔器", "塔", [("材质", "", ""), ("塔径", "mm", ""), ("塔高", "mm", ""), ("填料 / 塔板", "", "类型与数量"),
                   ("设计压力", "MPa", ""), ("设计温度", "℃", "")] + MAKER),
]

HEAD = PatternFill("solid", fgColor="DDEBF7")


def _sheet(wb, title, header, rows, widths):
    ws = wb.create_sheet(title)
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEAD
    for r in rows:
        ws.append(list(r))
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    for row in ws.iter_rows():
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")


def build(force: bool = False) -> None:
    if TARGET.exists() and not force:
        print(f"已存在，未覆盖：{TARGET}（--force 覆盖）")
        return
    wb = Workbook()
    wb.remove(wb.active)
    rows = [(name, kw, p, unit, note) for name, kw, params in TEMPLATES for p, unit, note in params]
    _sheet(wb, "参数模板", ["模板", "匹配关键字", "参数名", "单位", "说明"], rows, [16, 30, 16, 8, 50])
    _sheet(wb, "参数值", ["对象名称", "参数名", "值", "依据 / 来源", "状态"], [], [26, 16, 20, 30, 16])
    _sheet(wb, "说明", ["项", "内容"], [
        ("用途", "设备的固定参数（材质、容积、高度、电机功率等），显示在设备「参数 · 仪表」页签的「设计参数」分类里"),
        ("匹配", "设备先按设备名称、再按设备组声明的设备类型，命中「参数模板」里第一个匹配关键字的模板"),
        ("填值", "在「参数值」表按 对象名称（设备名或设备组名）+ 参数名 填写；设备组上的值对组内每台生效，设备上的值优先"),
        ("状态", "建议填 已确认 / 待确认；依据写铭牌、设备档案、图纸编号等"),
        ("生效", "改完后重启后端；单文件版需重新导出（python3 -m backend.tools.export_static）"),
    ], [10, 90])
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    wb.save(TARGET)
    print(f"已生成：{TARGET}（{len(TEMPLATES)} 个模板、{len(rows)} 个参数定义）")


if __name__ == "__main__":
    build(force="--force" in sys.argv)
