"""生成规则 Excel 空模板 6APA_规则.模板.xlsx。

模板只含表头、字段说明与填写示例 Sheet，**不含任何生产规则数据**。
需求文档第十三、二十四章明确规定：规则必须来自独立规则 Excel / 规则文件，
禁止根据参数名称自动生成生产判断规则。

填好后另存为 data/source/6APA_规则.xlsx，本体服务会自动加载。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.services.rule_loader import RULE_FIELD_LABELS, SHEET_RULES  # noqa: E402

OUT_FILE = ROOT / "data" / "source" / "6APA_规则.模板.xlsx"

FIELD_NOTES = [
    ("规则编号 (Rule ID)", "必填", "规则唯一编号，例如 R001"),
    ("规则名称 (Rule Name)", "必填", "规则中文名称，例如 泵运行状态一致性检查"),
    ("适用对象类型 (Applies To Type)", "必填", "设备 / 参数 / 工段 / 关系对象"),
    ("适用对象 (Applies To)", "必填", "适用对象名称，需与 DCS 点表设备名或参数语义名称一致，多个用顿号分隔"),
    ("适用工段 (Area)", "选填", "留空表示全工段适用"),
    ("条件 (Condition)", "必填", "触发条件，例如 启停指令 = 启动"),
    ("逻辑 (Logic)", "选填", "多条件之间的逻辑，例如 AND / OR"),
    ("阈值 (Threshold)", "选填", "数值阈值与单位，例如 > 35 ℃"),
    ("推理结论 (Conclusion)", "必填", "满足条件后得出的结论，例如 设备状态异常"),
    ("严重程度 (Severity)", "选填", "提示 / 警告 / 严重"),
    ("规则说明 (Description)", "选填", "规则的工艺含义与判断依据"),
]


def main() -> int:
    empty = pd.DataFrame(columns=RULE_FIELD_LABELS)
    notes = pd.DataFrame(FIELD_NOTES, columns=["字段", "是否必填", "填写说明"])
    readme = pd.DataFrame(
        [
            ["用途", "本模板用于录入 6-APA 生产线的推理规则，是本体服务的独立规则数据源。"],
            ["填写位置", f"在 Sheet「{SHEET_RULES}」中按行录入，每行一条规则。"],
            ["生效方式", "填好后另存为 data/source/6APA_规则.xlsx，重启本体服务即自动加载。"],
            ["重要约束", "规则不得由系统根据参数名称或关系谓词自动生成；本模板出厂为空表，不含任何示例规则数据。"],
            ["对象对齐", "“适用对象”建议填写 DCS 点表中的设备名称或参数语义名称，以便与本体实例关联。"],
        ],
        columns=["项目", "说明"],
    )

    with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as writer:
        empty.to_excel(writer, sheet_name=SHEET_RULES, index=False)
        notes.to_excel(writer, sheet_name="字段说明", index=False)
        readme.to_excel(writer, sheet_name="使用说明", index=False)
        fill = PatternFill("solid", fgColor="1F3A5F")
        widths = {SHEET_RULES: [16, 28, 22, 34, 18, 30, 12, 18, 28, 14, 44],
                  "字段说明": [30, 12, 60], "使用说明": [14, 80]}
        for sheet, ws in writer.sheets.items():
            for j in range(1, ws.max_column + 1):
                cell = ws.cell(row=1, column=j)
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = fill
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                ws.column_dimensions[get_column_letter(j)].width = widths[sheet][j - 1]
            ws.freeze_panes = "A2"

    print(f"✓ 写出 {OUT_FILE.name}（{SHEET_RULES} 为空表，仅表头）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
