"""空间层级：装置 → 单元 → 画面 → 设备组 / 设备（配置表沿用 车间 / 工艺段 / 工序 的表名）。

层级定义读 data/config/空间层级.xlsx；设备来自复制过来的点表加载结果（store.dcs）。
工序 = 一张流程画面。设备按「工段编号 + 设备匹配正则」归到工序，设备组像文件夹，
成员可分属两道工序，各工序只列本工序认领的成员。
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "data" / "config" / "空间层级.xlsx"

# 工序下固定挂 4 个节点
OP_SECTIONS = [
    ("devices", "设备", "设备组与设备"),
    ("calc", "计算组态", "本工序的派生量 / 指标计算定义"),
    ("cond", "工况与根因", "现象定义与根因影响关系"),
    ("docs", "文档提取", "规程、SOP 等文档及从中提取的本体对象"),
]


def _rows(ws) -> list[dict[str, Any]]:
    it = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it)]
    out = []
    for row in it:
        if not any(v not in (None, "") for v in row):
            continue
        out.append({h: (v.strip() if isinstance(v, str) else v) for h, v in zip(header, row)})
    return out


class Hierarchy:
    def __init__(self, store: Any, config_file: Path = CONFIG_FILE) -> None:
        if not config_file.exists():
            raise FileNotFoundError(f"缺少层级配置表 {config_file}，先运行 python3 -m backend.tools.build_cryo_sources")
        wb = load_workbook(config_file, read_only=True, data_only=True)
        source = config_file.name
        self.workshops = [
            {"id": r["车间编号"], "name": r["车间名称"], "description": r.get("说明") or "", "status": r.get("状态") or ""}
            for r in _rows(wb["车间"])
        ]
        self.segments: dict[str, dict[str, Any]] = {}
        for r in sorted(_rows(wb["工艺段"]), key=lambda r: r.get("顺序") or 0):
            self.segments[r["工艺段编号"]] = {
                "id": r["工艺段编号"], "workshopId": r["车间编号"], "name": r["工艺段名称"],
                "order": r.get("顺序") or 0, "description": r.get("说明") or "", "opIds": [],
            }
        self.ops: dict[str, dict[str, Any]] = {}
        for r in sorted(_rows(wb["工序"]), key=lambda r: (r["工艺段编号"], r.get("顺序") or 0)):
            op = {
                "id": r["工序编号"], "segmentId": r["工艺段编号"], "name": r["工序名称"], "order": r.get("顺序") or 0,
                "screen": r.get("流程画面") or "", "areaCodes": [c.strip() for c in str(r.get("工段编号") or "").split(",") if c.strip()],
                "match": r.get("设备匹配(正则)") or "",
                "subSteps": [s for s in re.split(r"[、,，]", r.get("子工序(写在图纸上)") or "") if s],
                "note": r.get("说明") or "", "status": r.get("状态") or "",
                "source": {"file": source, "sheet": "工序"},
            }
            self.ops[op["id"]] = op
            self.segments[op["segmentId"]]["opIds"].append(op["id"])
        self.not_included = _rows(wb["未纳入工段"]) if "未纳入工段" in wb.sheetnames else []
        self._assign(store)

    # ------------------------------------------------------------ 设备归属
    def _assign(self, store: Any) -> None:
        dcs = store.dcs
        by_area: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for op in self.ops.values():
            for code in op["areaCodes"]:
                by_area[code].append(op)
        self.op_of_equipment: dict[str, str] = {}
        for equip in dcs.equipment.values():
            candidates = by_area.get(equip.get("areaCode") or "")
            if not candidates:
                continue
            chosen = None
            for op in candidates:
                if op["match"] and re.search(op["match"], equip["name"]):
                    chosen = op
                    break
            if chosen is None:
                chosen = next((op for op in candidates if not op["match"]), candidates[0])
            self.op_of_equipment[equip["id"]] = chosen["id"]

        self.op_groups: dict[str, list[str]] = defaultdict(list)  # 工序 → 设备组（有成员归本工序）
        self.op_group_members: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.op_ungrouped: dict[str, list[str]] = defaultdict(list)
        self.ops_of_group: dict[str, list[str]] = defaultdict(list)
        for gid, group in dcs.equipment_groups.items():
            seen: set[str] = set()
            group_area = group.get("areaCode") or ""
            for eid in group.get("equipmentIds") or []:
                if eid in seen or eid not in dcs.equipment:
                    continue
                seen.add(eid)
                op_id = self.op_of_equipment.get(eid)
                # 设备组只在自己工段的工序下展开；别的工段的共用设备不跨工段挂进来
                if not op_id or group_area not in self.ops[op_id]["areaCodes"]:
                    continue
                # 共用设备（主设备组不是本组）在本组也列出，但归属以主组为准
                self.op_group_members[(op_id, gid)].append(eid)
            for (op_id, g), members in list(self.op_group_members.items()):
                if g == gid and members and op_id not in self.ops_of_group[gid]:
                    self.ops_of_group[gid].append(op_id)
                    self.op_groups[op_id].append(gid)
        # 设备组没有任何成员时，按设备组自己的工段落到默认工序
        for gid, group in dcs.equipment_groups.items():
            if self.ops_of_group.get(gid):
                continue
            ops = by_area.get(group.get("areaCode") or "")
            if ops:
                op = next((o for o in ops if not o["match"]), ops[0])
                self.ops_of_group[gid].append(op["id"])
                self.op_groups[op["id"]].append(gid)
        for eid, op_id in self.op_of_equipment.items():
            if not dcs.equipment[eid].get("equipmentGroupId"):
                self.op_ungrouped[op_id].append(eid)
        for lst in self.op_groups.values():
            lst.sort(key=lambda g: dcs.equipment_groups[g]["name"])
        for key in list(self.op_group_members):
            self.op_group_members[key].sort(key=lambda e: _natural(dcs.equipment[e]["name"]))
        for lst in self.op_ungrouped.values():
            lst.sort(key=lambda e: _natural(dcs.equipment[e]["name"]))

    # ------------------------------------------------------------ 查询
    def op_equipment(self, op_id: str) -> list[str]:
        return [e for e, o in self.op_of_equipment.items() if o == op_id]

    def segment_of_op(self, op_id: str) -> dict[str, Any]:
        return self.segments[self.ops[op_id]["segmentId"]]

    def path(self, op_id: str) -> list[dict[str, str]]:
        op = self.ops[op_id]
        seg = self.segments[op["segmentId"]]
        ws = next(w for w in self.workshops if w["id"] == seg["workshopId"])
        return [{"id": ws["id"], "name": ws["name"]}, {"id": seg["id"], "name": seg["name"]}, {"id": op["id"], "name": op["name"]}]

    def ops_of_object(self, store: Any, object_id: str) -> list[str]:
        if object_id.startswith("equip-"):
            op = self.op_of_equipment.get(object_id)
            return [op] if op else []
        if object_id.startswith("egrp-"):
            return list(self.ops_of_group.get(object_id, []))
        return []


def _natural(text: str) -> list[Any]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]
