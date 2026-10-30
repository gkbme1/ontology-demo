"""DCS 点表 Excel 导入层。

回答"现场有什么"：生产工段 / 控制站 / 标准设备组 / 设备 / 参数语义 / DCS 点。
本模块只读取 6APA_DCS.xlsx，不产生任何关系数据。

v2 起的口径变化（重要）
----------------------
旧版的「生产工段名称 (Process Area)」实际是按 **DCS 控制站** 划分的，一个控制站里
混着多个工艺工段（站13 同时含水解辅料、酶法水解、萃取与反萃、结晶辅料）。
v2 改用流程图口径的「工段编号(流程图口径)」+「工艺工段(流程图口径)」，
两者一一对应，共 24 个取值（S01–S23、S99）。控制站从"分类依据"降级为"属性"。

由此带来一处模型变化：**设备不再只属于一个工段**。1340 台设备（按设备归并表合并前）中有 46 台的点位
落在多个工段。处理方式是 areaId 仍给主工段（取自「设备统计」的声明），
另加 areaIds / areaCodes 列出实际覆盖的全部工段，过滤时按任一命中。
设备与控制站仍是一对一（已核查：0 台设备跨站），station 字段含义不变。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from backend.ontology import identifiers as ids
from backend.ontology.models import SOURCE_DCS, SOURCE_SCHEMA, Provenance
from backend.services.excel_utils import (
    read_sheet,
    HeaderMap,
    clean as _clean,
    find_header_row,
    norm_header,
    read_rows,
    to_int as _int,
)

SHEET_EQUIPMENT_STATS = "设备统计"
SHEET_TAG_DETAIL = "DCS点位明细"
SHEET_SCHEMA = "本体架构与设计规范(Schema)"
SHEET_AREAS = "工段划分"
SHEET_EQUIPMENT_GROUPS = "设备主数据"
SHEET_SCREEN_EXTRA = "画面补充测点"
SHEET_SCREEN_DIFF = "画面与点表差异"

# 编号解析不出来时的兜底工段（与点表「工段划分」中 S99 的含义一致）
FALLBACK_AREA_CODE = "S99"
FALLBACK_AREA_NAME = "备用/未定义点"

TAG_SPEC: dict[str, tuple[str, ...]] = {
    "tagName": ("DCS点名 (Tag PN)", "DCS点名"),
    "rawDescription": ("原点描述 (DCS Description)", "原点描述"),
    "station": ("控制站 (SN)", "控制站"),
    "legacyAreaName": ("所属工段 (Process Area)", "所属工段"),
    "equipmentName": ("生产设备/装置 (Equipment Entity)", "生产设备/装置"),
    "parameterName": ("参数语义名称 (Parameter Name)", "参数语义名称"),
    "parameterType": ("参数分类 (Parameter Type)", "参数分类"),
    "unit": ("工程单位 (Unit)", "工程单位"),
    "blockType": ("DCS块类型 (Block Type)", "DCS块类型"),
    "owlSubject": ("本体三元组主体 (OWL Subject URI)", "本体三元组主体"),
    # v2 新增
    "areaCode": ("工段编号(流程图口径)", "工段编号"),
    "areaName": ("工艺工段(流程图口径)", "工艺工段"),
    "equipmentGroupLabel": ("标准设备组(本体)", "标准设备组"),
    "equipmentGroupUri": ("标准设备组URI",),
    "boundProperty": ("绑定本体属性",),
    "variableCategory": ("变量类别",),
    "standardUnit": ("标准单位",),
    "processScreen": ("所在流程画面",),
    "attributionBasis": ("归属依据",),
    "confidence": ("归属置信度",),
}

STATS_SPEC: dict[str, tuple[str, ...]] = {
    "station": ("控制站(SN)", "控制站"),
    "legacyAreaName": ("生产工段名称 (Process Area)", "生产工段名称"),
    "equipmentName": ("生产设备/装置名称 (Equipment Entity)", "生产设备/装置名称"),
    "totalPoints": ("总点位数",),
    "pv": ("过程测量(PV)",),
    "op": ("控制输出(OP)",),
    "mot": ("电机控制(MOT)",),
    "val": ("阀门控制(VAL)",),
    "dido": ("开关反馈(DI/DO)",),
    "overview": ("核心参数/测点概览",),
    # v2 新增
    "areaCode": ("工段编号(流程图口径)", "工段编号"),
    "areaName": ("工艺工段(流程图口径)", "工艺工段"),
    "equipmentGroupLabel": ("标准设备组(本体)", "标准设备组"),
    "confidence": ("归属置信度",),
    "note": ("说明",),
}

_AREA_SPLIT = re.compile(r"^(?P<zh>[^(（]+)[\s(（]*(?P<en>[^)）]*)[)）]?\s*$")
_AREA_CODE = re.compile(r"^S\d{2}$", re.IGNORECASE)


def split_area_name(area_name: str) -> tuple[str, str | None]:
    """把「酶法水解工段 (Enzymatic Hydrolysis)」拆成中英文两段。

    v2 的工段名本身不带英文括号，拆出来 en 为 None，由「工段划分」Sheet 的
    「英文标识」列补上。这个函数保留是因为旧口径的名称还出现在若干存档字段里。
    """
    m = _AREA_SPLIT.match(area_name.strip())
    if not m:
        return area_name.strip(), None
    return m.group("zh").strip(), (m.group("en").strip() or None)


def normalize_area_code(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    text = text.strip().upper()
    return text if _AREA_CODE.match(text) else None


class DcsDataset:
    """DCS 点表加载结果。"""

    def __init__(self, file_name: str) -> None:
        self.file = file_name
        self.areas: dict[str, dict[str, Any]] = {}
        self.equipment: dict[str, dict[str, Any]] = {}
        self.parameters: dict[str, dict[str, Any]] = {}
        self.tags: dict[str, dict[str, Any]] = {}
        self.stations: dict[str, dict[str, Any]] = {}
        self.equipment_groups: dict[str, dict[str, Any]] = {}
        self.stats_rows: list[dict[str, Any]] = []
        self.schema_rows: list[dict[str, Any]] = []
        self.screen_extra_rows: list[dict[str, Any]] = []
        self.screen_diff_rows: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.load_stats: dict[str, Any] = {}
        self.merge_stats: dict[str, Any] | None = None
        # 工段编号 → areaId，供其它加载器按编号或名称回查
        self.area_by_code: dict[str, str] = {}
        self.area_by_name: dict[str, str] = {}
        # 按名称回查设备/参数：关系对象匹配要对 1174 个对象各查一次，
        # 逐次全表扫描是 O(对象数 × 实例数)，先建索引
        self._equipment_name_index: dict[str, list[dict[str, Any]]] = {}
        self._parameter_name_index: dict[str, list[dict[str, Any]]] = {}

    # 索引 -------------------------------------------------------------
    def equipment_by_owl(self, owl_subject: str) -> dict[str, Any] | None:
        return self.equipment.get(ids.equipment_id(owl_subject))

    def equipment_by_name(self, name: str) -> list[dict[str, Any]]:
        return self._equipment_name_index.get(name, [])

    def parameters_by_name(self, name: str) -> list[dict[str, Any]]:
        return self._parameter_name_index.get(name, [])

    def resolve_area(self, value: Any) -> str | None:
        """把 area-S01 / S01 / 工段全名 都归一成 areaId，取不到返回 None。"""
        text = _clean(value)
        if not text:
            return None
        if text in self.areas:
            return text
        code = normalize_area_code(text) or normalize_area_code(text[5:] if text.lower().startswith("area-") else "")
        if code and code in self.area_by_code:
            return self.area_by_code[code]
        by_name = self.area_by_name.get(norm_header(text))
        if by_name:
            return by_name
        return None

    def tag_by_name(self, tag_name: str) -> dict[str, Any] | None:
        return self.tags.get(ids.tag_id(tag_name))


def load_dcs(path: str | Path, merge_path: str | Path | None = None) -> DcsDataset:
    """加载 DCS 点表。merge_path 指向设备归并表时，按表把同一台设备的多种写法合并成一台。"""
    path = Path(path)
    ds = DcsDataset(path.name)

    raw_schema = read_sheet(path, SHEET_SCHEMA, header=None)
    _load_schema(ds, raw_schema)

    # 工段必须先于点位加载：点位要按编号挂到工段上
    _load_areas(ds, path)
    _load_equipment_groups(ds, path)
    _load_tags(ds, path)
    _load_stats(ds, path)
    _load_screen_sheets(ds, path)
    ds.merge_stats = None
    if merge_path is not None:
        from backend.services import equipment_merge

        merge_path = Path(merge_path)
        ds.merge_stats = equipment_merge.apply(ds, equipment_merge.load_table(merge_path), merge_path.name)
        ds.merge_stats["available"] = merge_path.exists()
    _finalise(ds)
    return ds


# --------------------------------------------------------------------- Schema


def _load_schema(ds: DcsDataset, raw: pd.DataFrame) -> None:
    header_row = None
    for i in range(len(raw)):
        if _clean(raw.iloc[i, 0]) == "本体建模要素":
            header_row = i
            break
    if header_row is None:
        return
    cols = ["element", "uri", "labelZh", "domain", "range", "example"]
    for i in range(header_row + 1, len(raw)):
        row = raw.iloc[i]
        element = _clean(row.iloc[0])
        if not element:
            continue
        item = {cols[j]: _clean(row.iloc[j]) for j in range(min(len(cols), len(row)))}
        item["sourceType"] = SOURCE_SCHEMA
        item["source"] = Provenance(ds.file, SHEET_SCHEMA, i + 1).to_dict()
        ds.schema_rows.append(item)


# ------------------------------------------------------------------ 工段划分


_AREA_SHEET_COLS = [
    "code", "name", "nameEn", "uri", "processScreens", "stationsDeclared",
    "positioning", "upstreamRaw", "downstreamRaw",
    "tagCountDeclared", "highConfidenceDeclared", "screenVisibleDeclared",
    "groupCountDeclared", "propertyCountDeclared",
]


def _parse_area_links(value: str | None) -> list[dict[str, str | None]]:
    """把「S03(稀硫酸)；S04(破乳剂溶液)」解析成结构化的上下游列表。"""
    text = _clean(value)
    if not text:
        return []
    links: list[dict[str, str | None]] = []
    for part in re.split(r"[；;]", text):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^\s*(S\d{2})\s*(.*)$", part, re.IGNORECASE)
        if m:
            material = m.group(2).strip()
            if material[:1] in "(（" and material[-1:] in ")）":
                material = material[1:-1].strip()
            links.append({"code": m.group(1).upper(), "material": material or None})
        else:
            links.append({"code": None, "material": part})
    return links


def _load_areas(ds: DcsDataset, path: Path) -> None:
    """工段以「工段划分」Sheet 为权威定义；该 Sheet 缺失时退回从点位里归纳。"""
    try:
        raw = read_sheet(path, SHEET_AREAS, header=None)
    except ValueError:
        ds.issues.append({
            "severity": "warning",
            "check": "工段定义表缺失",
            "detail": f"未找到 Sheet「{SHEET_AREAS}」，工段信息将只能从点位明细归纳，缺少英文标识/工艺定位/上下游。",
            "source": Provenance(ds.file, SHEET_AREAS).to_dict(),
        })
        return

    header_row = find_header_row(raw, "工段编号", limit=12)
    if header_row is None:
        return
    for i in range(header_row + 1, len(raw)):
        row = raw.iloc[i]
        code = normalize_area_code(row.iloc[0])
        if not code:
            continue  # "合计" 行等
        rec = {
            _AREA_SHEET_COLS[j]: _clean(row.iloc[j])
            for j in range(min(len(_AREA_SHEET_COLS), len(row)))
        }
        name = rec.get("name") or code
        aid = ids.area_id(code)
        ds.areas[aid] = {
            "id": aid,
            "code": code,
            "name": name,
            "nameZh": name,
            "nameEn": rec.get("nameEn"),
            "uri": rec.get("uri"),
            "processScreens": [s.strip() for s in re.split(r"[/、,，]", rec.get("processScreens") or "") if s.strip()],
            "positioning": rec.get("positioning"),
            "upstream": _parse_area_links(rec.get("upstreamRaw")),
            "downstream": _parse_area_links(rec.get("downstreamRaw")),
            "declared": {
                "stations": rec.get("stationsDeclared"),
                "tagCount": _int(rec.get("tagCountDeclared")),
                "highConfidenceCount": _int(rec.get("highConfidenceDeclared")),
                "screenVisibleCount": _int(rec.get("screenVisibleDeclared")),
                "equipmentGroupCount": _int(rec.get("groupCountDeclared")),
                "propertyCount": _int(rec.get("propertyCountDeclared")),
            },
            "stations": [],
            "equipmentIds": [],
            "tagIds": [],
            "parameterIds": [],
            "equipmentGroupIds": [],
            "confidenceCounts": {},
            "sourceType": SOURCE_DCS,
            "source": Provenance(ds.file, SHEET_AREAS, i + 1, "工段编号", code).to_dict(),
        }
        ds.area_by_code[code] = aid
        ds.area_by_name[norm_header(name)] = aid


def _ensure_area(ds: DcsDataset, code: str, name: str | None, row: int) -> dict[str, Any]:
    """点位里出现了「工段划分」没登记的编号时兜底建一个，并报 warning。"""
    aid = ids.area_id(code)
    area = ds.areas.get(aid)
    if area is not None:
        return area
    area = {
        "id": aid, "code": code, "name": name or code, "nameZh": name or code, "nameEn": None,
        "uri": None, "processScreens": [], "positioning": None, "upstream": [], "downstream": [],
        "declared": {}, "stations": [], "equipmentIds": [], "tagIds": [], "parameterIds": [],
        "equipmentGroupIds": [], "confidenceCounts": {},
        "sourceType": SOURCE_DCS,
        "source": Provenance(ds.file, SHEET_TAG_DETAIL, row, "工段编号(流程图口径)", code).to_dict(),
    }
    ds.areas[aid] = area
    ds.area_by_code[code] = aid
    if name:
        ds.area_by_name[norm_header(name)] = aid
    ds.issues.append({
        "severity": "warning",
        "check": "工段编号未在工段划分表中登记",
        "detail": f"点位明细出现工段编号 {code}（{name or '无名称'}），但「{SHEET_AREAS}」中没有该条目。",
        "source": area["source"],
    })
    return area


# -------------------------------------------------------------- 标准设备组


_GROUP_COLS = [
    "uri", "name", "areaCode", "areaName", "equipmentType", "instanceCount",
    "instanceList", "components", "keyTags", "properties", "tagCountDeclared",
]


def _split_list(value: str | None) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    return [p.strip() for p in re.split(r"[、,，;；]", text) if p.strip()]


def _load_equipment_groups(ds: DcsDataset, path: Path) -> None:
    try:
        raw = read_sheet(path, SHEET_EQUIPMENT_GROUPS, header=None)
    except ValueError:
        return
    header_row = find_header_row(raw, "设备组URI", limit=12)
    if header_row is None:
        return
    for i in range(header_row + 1, len(raw)):
        row = raw.iloc[i]
        uri = _clean(row.iloc[0])
        if not uri:
            continue
        rec = {_GROUP_COLS[j]: _clean(row.iloc[j]) for j in range(min(len(_GROUP_COLS), len(row)))}
        name = rec.get("name")
        if not name:
            continue
        gid = ids.equipment_group_id(uri, name)
        code = normalize_area_code(rec.get("areaCode"))
        aid = ids.area_id(code) if code else None
        ds.equipment_groups[gid] = {
            "id": gid,
            "uri": uri,
            "name": name,
            "areaId": aid,
            "areaCode": code,
            "areaName": rec.get("areaName"),
            "equipmentType": rec.get("equipmentType"),
            "instanceCountDeclared": _int(rec.get("instanceCount")),
            "instances": _split_list(rec.get("instanceList")),
            "components": _split_list(rec.get("components")),
            "keyTags": rec.get("keyTags"),
            "properties": _split_list(rec.get("properties")),
            "tagCountDeclared": _int(rec.get("tagCountDeclared")),
            "tagIds": [],
            "equipmentIds": [],
            "sourceType": SOURCE_DCS,
            "source": Provenance(ds.file, SHEET_EQUIPMENT_GROUPS, i + 1, "设备组名称", name).to_dict(),
        }
        if aid and aid in ds.areas and gid not in ds.areas[aid]["equipmentGroupIds"]:
            ds.areas[aid]["equipmentGroupIds"].append(gid)


# ----------------------------------------------------------------- 点位明细


def _load_tags(ds: DcsDataset, path: Path) -> None:
    hm, rows, start = read_rows(path, SHEET_TAG_DETAIL, TAG_SPEC)
    if hm.missing:
        ds.issues.append({
            "severity": "warning",
            "check": "点位明细缺列",
            "detail": "未找到列：" + "、".join(hm.missing),
            "source": Provenance(ds.file, SHEET_TAG_DETAIL).to_dict(),
        })
    group_by_name = {g["name"]: g for g in ds.equipment_groups.values()}
    group_by_uri = {g["uri"]: g for g in ds.equipment_groups.values()}

    for offset, row in enumerate(rows):
        i = start + offset
        tag_name = hm.text(row, "tagName")
        if not tag_name:
            continue
        owl_subject = hm.text(row, "owlSubject")
        equipment_name = hm.text(row, "equipmentName")
        parameter_name = hm.text(row, "parameterName")
        station = hm.text(row, "station")
        src = Provenance(ds.file, SHEET_TAG_DETAIL, i).to_dict()

        # 工段：编号为准，名称仅作展示与兜底登记
        code = normalize_area_code(hm.text(row, "areaCode")) or FALLBACK_AREA_CODE
        area_name = hm.text(row, "areaName") or (FALLBACK_AREA_NAME if code == FALLBACK_AREA_CODE else None)
        area = _ensure_area(ds, code, area_name, i)
        aid = area["id"]
        if station and station not in area["stations"]:
            area["stations"].append(station)
        confidence = hm.text(row, "confidence")
        if confidence:
            area["confidenceCounts"][confidence] = area["confidenceCounts"].get(confidence, 0) + 1

        # 控制站
        if station:
            st = ds.stations.setdefault(
                station,
                {"id": f"station-{station}", "sn": station, "areaIds": [], "tagCount": 0, "sourceType": SOURCE_DCS},
            )
            st["tagCount"] += 1
            if aid not in st["areaIds"]:
                st["areaIds"].append(aid)

        # 设备（以 OWL Subject URI 归并，需求第七章）
        eid = None
        if owl_subject:
            eid = ids.equipment_id(owl_subject)
            equip = ds.equipment.get(eid)
            if equip is None:
                equip = {
                    "id": eid,
                    "owlSubject": owl_subject,
                    "name": equipment_name or owl_subject,
                    "areaId": aid,          # 主工段，_load_stats 会用设备统计表的声明覆盖
                    "areaName": area["name"],
                    "areaCode": code,
                    "areaIds": [],
                    "areaCodes": [],
                    "station": station,
                    "parameterIds": [],
                    "tagIds": [],
                    "stats": {"total": 0, "pv": 0, "op": 0, "mot": 0, "val": 0, "dido": 0},
                    "statsFromSheet1": None,
                    "overview": None,
                    "equipmentGroup": None,
                    "equipmentGroupId": None,
                    "confidence": None,
                    "sourceType": SOURCE_DCS,
                    "source": Provenance(
                        ds.file, SHEET_TAG_DETAIL, i, "生产设备/装置 (Equipment Entity)", equipment_name
                    ).to_dict(),
                }
                ds.equipment[eid] = equip
            if code not in equip["areaCodes"]:
                equip["areaCodes"].append(code)
                equip["areaIds"].append(aid)
            if eid not in area["equipmentIds"]:
                area["equipmentIds"].append(eid)
            equip["stats"]["total"] += 1
            equip["tagIds"].append(ids.tag_id(tag_name))

        # 参数语义
        pid = None
        if owl_subject and parameter_name:
            pid = ids.parameter_id(owl_subject, parameter_name)
            param = ds.parameters.get(pid)
            if param is None:
                param = {
                    "id": pid,
                    "name": parameter_name,
                    "equipmentId": eid,
                    "equipmentName": equipment_name,
                    "owlSubject": owl_subject,
                    "areaId": aid,
                    "areaName": area["name"],
                    "areaCode": code,
                    "station": station,
                    "categories": [],
                    "units": [],
                    "blockTypes": [],
                    "tagIds": [],
                    "sourceType": SOURCE_DCS,
                    "source": Provenance(
                        ds.file, SHEET_TAG_DETAIL, i, "参数语义名称 (Parameter Name)", parameter_name
                    ).to_dict(),
                }
                ds.parameters[pid] = param
                if eid:
                    ds.equipment[eid]["parameterIds"].append(pid)
            if pid not in area["parameterIds"]:
                area["parameterIds"].append(pid)
            ptype = hm.text(row, "parameterType")
            unit = hm.text(row, "unit")
            block = hm.text(row, "blockType")
            for key, value in (("categories", ptype), ("units", unit), ("blockTypes", block)):
                if value and value not in param[key]:
                    param[key].append(value)
            param["tagIds"].append(ids.tag_id(tag_name))

        # 标准设备组：点表里的写法比设备主数据细，先按名称/URI 对齐，对不上就只留文字
        group_label = hm.text(row, "equipmentGroupLabel")
        group_uri = hm.text(row, "equipmentGroupUri")
        group = group_by_uri.get(group_uri or "") or group_by_name.get(group_label or "")

        # DCS 点
        tid = ids.tag_id(tag_name)
        tag = {
            "id": tid,
            "name": tag_name,
            "rawDescription": hm.text(row, "rawDescription"),
            "station": station,
            "areaId": aid,
            "areaName": area["name"],
            "areaCode": code,
            "equipmentId": eid,
            "equipmentName": equipment_name,
            "parameterId": pid,
            "parameterName": parameter_name,
            "parameterType": hm.text(row, "parameterType"),
            "unit": hm.text(row, "unit"),
            "blockType": hm.text(row, "blockType"),
            "owlSubject": owl_subject,
            # v2 新增
            "equipmentGroup": group_label,
            "equipmentGroupId": group["id"] if group else None,
            "equipmentGroupUri": group_uri or (group["uri"] if group else None),
            "boundProperty": hm.text(row, "boundProperty"),
            "variableCategory": hm.text(row, "variableCategory"),
            "standardUnit": hm.text(row, "standardUnit"),
            "processScreen": hm.text(row, "processScreen"),
            "attributionBasis": hm.text(row, "attributionBasis"),
            "confidence": confidence,
            "legacyAreaName": hm.text(row, "legacyAreaName"),
            "sourceType": SOURCE_DCS,
            "source": src,
        }
        if tid in ds.tags:
            ds.tags[tid].setdefault("duplicates", []).append(src)
        else:
            ds.tags[tid] = tag
        if tid not in area["tagIds"]:
            area["tagIds"].append(tid)
        if group:
            group["tagIds"].append(tid)
            if eid and eid not in group["equipmentIds"]:
                group["equipmentIds"].append(eid)

        if eid:
            _bump_stats(ds.equipment[eid]["stats"], tag["parameterType"])


_STAT_KEYS = {
    "过程测量(PV)": "pv",
    "控制输出(OP)": "op",
    "电机控制(MOT)": "mot",
    "阀门控制(VAL)": "val",
    "状态反馈(DI)": "dido",
    "开关控制(DO)": "dido",
}


def _bump_stats(stats: dict[str, int], parameter_type: str | None) -> None:
    key = _STAT_KEYS.get(parameter_type or "")
    if key:
        stats[key] += 1


# ----------------------------------------------------------------- 设备统计


def _load_stats(ds: DcsDataset, path: Path) -> None:
    hm, rows, start = read_rows(path, SHEET_EQUIPMENT_STATS, STATS_SPEC)
    group_by_name = {g["name"]: g for g in ds.equipment_groups.values()}

    for offset, row in enumerate(rows):
        i = start + offset
        equipment_name = hm.text(row, "equipmentName")
        if not equipment_name:
            continue
        station = hm.text(row, "station")
        if not station or not station.isdigit():
            continue  # 「合计」等汇总行，不是设备
        code = normalize_area_code(hm.text(row, "areaCode"))
        entry = {
            "station": station,
            "areaCode": code,
            "areaName": hm.text(row, "areaName"),
            "legacyAreaName": hm.text(row, "legacyAreaName"),
            "equipmentName": equipment_name,
            "totalPoints": _int(hm.get(row, "totalPoints")),
            "pv": _int(hm.get(row, "pv")),
            "op": _int(hm.get(row, "op")),
            "mot": _int(hm.get(row, "mot")),
            "val": _int(hm.get(row, "val")),
            "dido": _int(hm.get(row, "dido")),
            "overview": hm.text(row, "overview"),
            "equipmentGroupLabel": hm.text(row, "equipmentGroupLabel"),
            "confidence": hm.text(row, "confidence"),
            "note": hm.text(row, "note"),
            "sourceType": SOURCE_DCS,
            "source": Provenance(ds.file, SHEET_EQUIPMENT_STATS, i).to_dict(),
        }
        ds.stats_rows.append(entry)

        if not code:
            ds.issues.append({
                "severity": "warning",
                "check": "设备统计缺工段编号",
                "detail": f"设备「{equipment_name}」（站 {station}）没有填工段编号，归入 {FALLBACK_AREA_CODE}。",
                "source": entry["source"],
            })

        # Sheet1 没有 OWL Subject 列，按 Schema Sheet 约定的命名规则
        # `:Dev_<控制站>_<设备名>` 回指点位明细中的同一设备实例。
        # 这是同一份 DCS Excel 内部两张表的关联，不是跨数据源的名称推断；
        # 拼不出或拼错时退回到「同站同名且唯一」才认定，否则记为未回指。
        owl_candidate = f":Dev_{station}_{equipment_name}" if station else None
        equip = ds.equipment_by_owl(owl_candidate) if owl_candidate else None
        if equip is None:
            candidates = [
                e for e in ds.equipment.values()
                if e["name"] == equipment_name and e["station"] == station
            ]
            equip = candidates[0] if len(candidates) == 1 else None
        if equip is None:
            continue

        equip["statsFromSheet1"] = {k: entry[k] for k in ("totalPoints", "pv", "op", "mot", "val", "dido")}
        equip["overview"] = entry["overview"]
        equip["statsSource"] = entry["source"]
        equip["confidence"] = entry["confidence"]
        equip["note"] = entry["note"]
        entry["equipmentId"] = equip["id"]

        # 主工段以设备统计的声明为准
        primary = ids.area_id(code) if code else None
        if primary and primary in ds.areas:
            equip["areaId"] = primary
            equip["areaCode"] = code
            equip["areaName"] = ds.areas[primary]["name"]
            if primary not in equip["areaIds"]:
                equip["areaIds"].insert(0, primary)
                equip["areaCodes"].insert(0, code)
                ds.areas[primary]["equipmentIds"].append(equip["id"])

        group = group_by_name.get(entry["equipmentGroupLabel"] or "")
        equip["equipmentGroup"] = entry["equipmentGroupLabel"]
        if group:
            equip["equipmentGroupId"] = group["id"]
            if equip["id"] not in group["equipmentIds"]:
                group["equipmentIds"].append(equip["id"])


# ------------------------------------------------------- 画面补充测点 / 差异


def _load_screen_sheets(ds: DcsDataset, path: Path) -> None:
    for sheet, marker, cols, bucket in (
        (SHEET_SCREEN_EXTRA, "画面位号", ["tag", "screen", "meaning", "areaCode", "suggestedGroup", "status"], ds.screen_extra_rows),
        (SHEET_SCREEN_DIFF, "位号/对象", ["tag", "screen", "screenLabel", "tableLabel", "impact", "confirmed"], ds.screen_diff_rows),
    ):
        try:
            raw = read_sheet(path, sheet, header=None)
        except ValueError:
            continue
        header_row = find_header_row(raw, marker, limit=12)
        if header_row is None:
            continue
        for i in range(header_row + 1, len(raw)):
            row = raw.iloc[i]
            first = _clean(row.iloc[0])
            if not first:
                continue
            item = {cols[j]: _clean(row.iloc[j]) for j in range(min(len(cols), len(row)))}
            item["sourceType"] = SOURCE_DCS
            item["source"] = Provenance(ds.file, sheet, i + 1).to_dict()
            bucket.append(item)


def _finalise(ds: DcsDataset) -> None:
    ds._equipment_name_index = {}
    for equip in ds.equipment.values():
        ds._equipment_name_index.setdefault(equip["name"], []).append(equip)
        # 归并前的写法仍可按名称查到合并后的设备
        for alias in equip.get("aliases") or []:
            bucket = ds._equipment_name_index.setdefault(alias["name"], [])
            if equip not in bucket:
                bucket.append(equip)
    ds._parameter_name_index = {}
    for param in ds.parameters.values():
        ds._parameter_name_index.setdefault(param["name"], []).append(param)

    for area in ds.areas.values():
        area["equipmentIds"] = list(dict.fromkeys(area["equipmentIds"]))
        area["equipmentCount"] = len(area["equipmentIds"])
        area["tagCount"] = len(area["tagIds"])
        area["parameterCount"] = len(area["parameterIds"])
        area["equipmentGroupCount"] = len(area["equipmentGroupIds"])
        area["stations"].sort(key=lambda s: (len(s), s))
    for equip in ds.equipment.values():
        equip["parameterCount"] = len(equip["parameterIds"])
        equip["tagCount"] = len(equip["tagIds"])
        equip["areaSpan"] = len(equip["areaIds"])
        equip["areaNames"] = [ds.areas[a]["name"] for a in equip["areaIds"] if a in ds.areas]
    for param in ds.parameters.values():
        param["tagCount"] = len(param["tagIds"])
    for group in ds.equipment_groups.values():
        group["tagCount"] = len(group["tagIds"])
        group["equipmentCount"] = len(group["equipmentIds"])

    ds.load_stats = {
        "file": ds.file,
        "sheets": [
            {"sheet": SHEET_AREAS, "rows": len(ds.areas), "validRows": len(ds.areas)},
            {
                "sheet": SHEET_EQUIPMENT_STATS,
                "rows": len(ds.stats_rows),
                "validRows": len([r for r in ds.stats_rows if r["equipmentName"]]),
            },
            {"sheet": SHEET_TAG_DETAIL, "rows": len(ds.tags), "validRows": len(ds.tags)},
            {
                "sheet": SHEET_EQUIPMENT_GROUPS,
                "rows": len(ds.equipment_groups),
                "validRows": len(ds.equipment_groups),
            },
            {"sheet": SHEET_SCHEMA, "rows": len(ds.schema_rows), "validRows": len(ds.schema_rows)},
            {
                "sheet": SHEET_SCREEN_EXTRA,
                "rows": len(ds.screen_extra_rows),
                "validRows": len(ds.screen_extra_rows),
            },
            {
                "sheet": SHEET_SCREEN_DIFF,
                "rows": len(ds.screen_diff_rows),
                "validRows": len(ds.screen_diff_rows),
            },
        ],
        "areaCount": len(ds.areas),
        "equipmentCount": len(ds.equipment),
        "parameterCount": len(ds.parameters),
        "tagCount": len(ds.tags),
        "stationCount": len(ds.stations),
        "equipmentGroupCount": len(ds.equipment_groups),
        "multiAreaEquipmentCount": len([e for e in ds.equipment.values() if e["areaSpan"] > 1]),
        "equipmentMerge": ds.merge_stats,
    }
