"""生成实例连接表 data/source/6APA_实例连接.xlsx。

    python3 -m backend.tools.build_instance_links          # 生成（已存在时不覆盖）
    python3 -m backend.tools.build_instance_links --force  # 按规则重新判断，覆盖人工改过的连接方式

「组连接方式」工作表：每条组间（或物料—设备组）关系一行，给出自动判断的连接方式；
可改「连接方式」（单台直连 / 按台号 / 汇管 / 指定 / 不展开 / 物料到各台）与「指定连接」（如 A→A；B→C）。
「实例连接（推导结果）」工作表只供查看，本体服务加载时按「组连接方式」重新推导。规则见 backend/services/instance_links.py。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.ontology.indexes import OntologyStore  # noqa: E402
from backend.services import instance_links as il  # noqa: E402

OUT_FILE = ROOT / "data" / "source" / il.LINK_FILE_NAME


def _style(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions


def main() -> int:
    if OUT_FILE.exists() and "--force" not in sys.argv:
        print(f"{OUT_FILE.name} 已存在，未覆盖（按规则重新判断请加 --force）")
        return 0
    store = OntologyStore()
    links = il.build(store)  # 不读旧表：全部按规则自动判断
    modes = [{
        "关系编号": r["relationCode"], "关系类别": r["category"], "主体": r["subject"], "谓词": r["predicate"],
        "客体": r["object"], "主体实例": "、".join(r["subjectInstances"]) or "—", "客体实例": "、".join(r["objectInstances"]) or "—",
        "自动判断": r["auto"], "连接方式": r["mode"], "指定连接": "", "说明": r["autoReason"]
        + (f"；对不上：{'、'.join(r['missing'])}" if r["missing"] else ""), "依据": r["mechanism"],
    } for r in links.rows]
    derived = []
    seen = set()
    for views in links.by_equipment.values():
        for v in views:
            key = (v["relationId"], v["from"], v["to"])
            if key in seen:
                continue
            seen.add(key)
            derived.append({"关系编号": v["relationCode"], "主体实例": v["from"], "谓词": v["predicate"], "客体实例": v["to"],
                            "连接方式": v["mode"], "状态": v["status"], "组间关系": v["groupRelation"]})
    derived.sort(key=lambda r: (r["关系编号"], r["主体实例"], r["客体实例"]))
    notes = [
        ("三层", "类（设备类型，如 固定化酶反应罐）定义属性与可连接的类型；设备组（如 水解反应釜组）是一组真实设备；实例（如 水解罐A）是单台设备。"),
        ("为什么要这张表", "工业关系表的拓扑写在设备组之间，落到实例要先确定连接方式，不能原样当成实例的关系。"),
        ("连接方式", "单台直连：各一台；按台号：A→A、B→B；汇管：每台连对方每台；指定：在「指定连接」写 A→A；B→C；"
                  "不展开：只保留组间关系；物料到各台：物料 / 介质与组内每台相连。"),
        ("状态", "推导：规则可靠；推导·待确认：汇管、指定、对不全的按台号、无法展开，需现场确认；人工指定：改过连接方式。"),
        ("主体实例", "设备组里真正属于这一组的设备：优先取声明的实例，其次取与组同名的那台，再次按设备类型中心词（罐 / 机 / 器…）取，排除附属泵。"),
    ]
    with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as writer:
        pd.DataFrame(modes, columns=il.MODE_COLUMNS).to_excel(writer, sheet_name=il.SHEET_MODES, index=False)
        pd.DataFrame(derived).to_excel(writer, sheet_name=il.SHEET_LINKS, index=False)
        pd.DataFrame(notes, columns=["项目", "说明"]).to_excel(writer, sheet_name="说明", index=False)
        _style(writer.sheets[il.SHEET_MODES], [10, 12, 26, 10, 26, 30, 30, 10, 10, 18, 40, 40])
        _style(writer.sheets[il.SHEET_LINKS], [10, 22, 10, 22, 10, 12, 50])
        writer.sheets["说明"].column_dimensions["A"].width = 14
        writer.sheets["说明"].column_dimensions["B"].width = 120
    stats = links.load_stats
    print(f"已生成 {OUT_FILE.relative_to(ROOT)}：{stats['groupRelationCount']} 条组间关系，"
          f"推出 {stats['instanceLinkCount']} 条实例连接；连接方式 {stats['byMode']}；待确认 {stats['pendingCount']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
