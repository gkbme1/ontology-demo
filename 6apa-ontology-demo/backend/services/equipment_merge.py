"""设备名称统一与归并。

DCS 点表按位号描述里的设备名前缀切设备，同一台现场设备常被写成好几种名字，例如
水解罐A 的搅拌、温度写作「水解罐A…」，进料阀写作「A罐…」，RB 进料阀写作「A罐RB…」，
两支 pH 电极写作「水解罐A1/A2」，液位点又挂在另一个控制站。加载后就成了 6 台设备。

这里分两步处理，DCS Excel 本身不改：

1. propose(ds)：按下面的规则在同一标准设备组内找出应归并的设备，生成归并表
   （data/source/6APA_设备归并.xlsx，由 backend/tools/build_equipment_merge.py 写出）。
   表可以直接编辑：「启用」改成 否 即不归并，也可以手工追加行。
2. apply(ds, rows)：加载 DCS 点表时按归并表把设备合并成一台，统一名称；
   原设备的 ID、OWL Subject、名称都登记为别名，旧 ID 和旧名称仍能查到合并后的设备。

规则（都限定在同一标准设备组内，从严不从宽）：
- 本名 / 同名异写：与设备主数据声明的实例同名，或只差「配置/配制」、大小写；
- 简称：实例「水解罐A」被写作「A罐」（设备号 + 实例名末尾的字）；
- 冗余后缀：实例「浓硫酸储罐A」被写作「浓硫酸储罐A罐」；
- 省略设备位号：实例「破乳剂配置罐R2120D」被写作「破乳剂配制罐D」；
  组内同时有「水洗离心机X2141A」和「水洗离心机A」时，前者并入后者；
- 附属点位：「水解罐A1/A2」（声明实例 + 1~2 位序号，如双 pH 电极）、
  「A罐RB」「一萃轻相出料A泵GZ」（设备名 + 下面缩写表里的后缀）；
- 同名跨站：同组、同工段、同名而控制站不同的设备（如水解罐A 的液位点在 20 站）。
「公用测量管线」「其他工艺单元」「管网阀门系统」这类兜底名称不参与归并。
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.ontology import identifiers as ids

MERGE_FILE_NAME = "6APA_设备归并.xlsx"
SHEET = "设备归并"

# 附属点位后缀：只认这些缩写，避免把「成品罐AB」（A、B 两个罐）之类误并
COMPONENT_SUFFIXES = {
    "RB": "RB 进料",
    "PH": "pH 测点",
    "GZ": "故障信号",
    "YC": "远程信号",
    "YX": "运行信号",
}
# 兜底归类名称，不是具体设备
GENERIC_NAMES = {"公用测量管线", "其他工艺单元", "管网阀门系统"}

KIND_SAME = "同一设备"
KIND_COMPONENT = "附属点位"
KIND_RENAME = "统一名称"

COLUMNS = [
    "序号", "工段", "设备组", "原设备名", "控制站", "原OWL Subject", "点位数",
    "统一设备名", "统一OWL Subject", "归并方式", "规则", "依据", "参数前缀", "启用",
]

_CJK = re.compile(r"^[一-鿿]+$")
_INSTANCE = re.compile(r"^(.*?[一-鿿#)）])([A-Za-z0-9]+)$")


def _norm(name: str) -> str:
    return name.replace("配置", "配制").lower()


def _split_instance(name: str) -> tuple[str, str | None]:
    """「水解罐A」→（水解罐, A）；「破乳剂配置罐R2120D」→（破乳剂配置罐, R2120D）。"""
    m = _INSTANCE.match(name)
    return (m.group(1), m.group(2)) if m else (name, None)


def _match_instance(name: str, instances: list[str]) -> tuple[str, str, str] | None:
    """设备名对应到声明实例：返回（实例名, 规则, 依据）。"""
    for inst in instances:
        base, code = _split_instance(inst)
        if name == inst:
            return inst, "本名", "与设备主数据声明的实例同名"
        if _norm(name) == _norm(inst):
            return inst, "同名异写", f"「{name}」与实例「{inst}」只差写法（配置/配制、大小写）"
        if code and name.startswith(code):
            tail = name[len(code):]
            if tail and _CJK.match(tail) and base.endswith(tail):
                return inst, "简称", f"「{name}」= 设备号 {code} + 「{tail}」，是实例「{inst}」的简写"
        if name.startswith(inst) and name != inst:
            tail = name[len(inst):]
            if _CJK.match(tail) and base.endswith(tail):
                return inst, "冗余后缀", f"「{name}」比实例「{inst}」多写了一个「{tail}」"
        m = re.match(r"^(.*?)([A-Za-z])$", name)
        if code and m and _norm(m.group(1)) == _norm(base) and code.endswith(m.group(2)) \
                and re.match(r"^[A-Z]+\d+$", code[:-1]):
            return inst, "省略设备位号", f"「{name}」省略了实例「{inst}」中的设备位号 {code[:-1]}"
    return None


def propose(ds: Any) -> list[dict[str, Any]]:
    """按规则生成归并表（ds 为未归并的 DcsDataset）。"""
    rows: list[dict[str, Any]] = []
    for group in sorted(ds.equipment_groups.values(), key=lambda g: (g.get("areaCode") or "", g["name"])):
        members = [e for e in ds.equipment.values()
                   if e.get("equipmentGroupId") == group["id"] and e["name"] not in GENERIC_NAMES]
        if not members:
            continue
        instances = [i for i in group.get("instances") or [] if i]
        names = {e["name"] for e in members}

        # 1) 设备名 → 统一名称
        target: dict[str, tuple[str, str, str]] = {}
        for e in members:
            hit = _match_instance(e["name"], instances)
            if hit:
                target[e["id"]] = hit
        for e in members:
            if e["id"] in target:
                continue
            m = re.match(r"^(.*?[一-鿿])([A-Z]+\d{3,})([A-Za-z])$", e["name"])
            if m and (m.group(1) + m.group(3)) in names:
                short = m.group(1) + m.group(3)
                target[e["id"]] = (short, "省略设备位号", f"组内同时有「{short}」，「{e['name']}」带设备位号 {m.group(2)}，为同一台")

        # 2) 附属点位：设备名 = 某台设备（或其别名）+ 后缀
        resolved = {e["name"]: target.get(e["id"], (e["name"],))[0] for e in members}
        declared = set(instances)
        component: dict[str, str] = {}
        for e in members:
            if e["id"] in target or e["name"] in declared:
                continue
            for base in sorted(resolved, key=len, reverse=True):
                if base == e["name"] or not e["name"].startswith(base):
                    continue
                suffix = e["name"][len(base):]
                canon = resolved[base]
                if re.match(r"^\d{1,2}$", suffix) and canon in declared and re.search(r"[A-Za-z]$", base):
                    target[e["id"]] = (canon, "附属点位", f"「{e['name']}」= 实例「{canon}」+ 序号 {suffix}（同一设备上的第 {suffix} 支测量元件）")
                    component[e["id"]] = ""
                elif suffix.upper() in COMPONENT_SUFFIXES:
                    meaning = COMPONENT_SUFFIXES[suffix.upper()]
                    target[e["id"]] = (canon, "附属点位", f"「{e['name']}」= 「{base}」+ {suffix}（{meaning}）")
                    component[e["id"]] = suffix
                break

        # 3) 按统一名称成组；同名跨站的只并同工段的
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for e in members:
            canon = target.get(e["id"], (e["name"],))[0]
            buckets[(canon, e.get("areaCode") or "")].append(e)
        for (canon, _area), items in buckets.items():
            primary = max(items, key=lambda e: (e["name"] == canon, e["id"] not in component, e["tagCount"], e["owlSubject"]))
            for e in sorted(items, key=lambda e: (e is not primary, e["name"], e.get("station") or "")):
                rule, basis = target.get(e["id"], (canon, "", ""))[1:]
                if e is primary:
                    if e["name"] == canon:
                        continue
                    kind = KIND_RENAME
                elif e["id"] in component:
                    kind = KIND_COMPONENT
                else:
                    kind = KIND_SAME
                    if rule in ("", "本名"):
                        rule = "同名跨站"
                        basis = f"同组同工段同名，控制站 {e.get('station')} 与 {primary.get('station')} 不同"
                rows.append({
                    "工段": e.get("areaCode") or "",
                    "设备组": group["name"],
                    "原设备名": e["name"],
                    "控制站": e.get("station") or "",
                    "原OWL Subject": e["owlSubject"],
                    "点位数": e["tagCount"] if "tagCount" in e else len(e["tagIds"]),
                    "统一设备名": canon,
                    "统一OWL Subject": primary["owlSubject"],
                    "归并方式": kind,
                    "规则": rule,
                    "依据": basis,
                    "参数前缀": component.get(e["id"], ""),
                    "启用": "是",
                })
    for i, row in enumerate(rows, 1):
        row["序号"] = i
    return rows


# --------------------------------------------------------------------- 读表


def load_table(path: Path) -> list[dict[str, Any]]:
    """读取归并表；文件不存在时返回空表（即不做归并）。"""
    if not path.exists():
        return []
    import pandas as pd

    df = pd.read_excel(path, sheet_name=SHEET, dtype=str).fillna("")
    rows = []
    for i, rec in enumerate(df.to_dict("records")):
        row = {k: str(v).strip() for k, v in rec.items()}
        row["_row"] = i + 2
        rows.append(row)
    return rows


# --------------------------------------------------------------------- 归并


class AliasDict(dict):
    """设备 / 参数字典：遍历只给出合并后的对象，按旧 ID 取值时转到合并后的对象。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.aliases: dict[str, str] = {}

    def resolve(self, key: str) -> str:
        seen = set()
        while not dict.__contains__(self, key) and key in self.aliases and key not in seen:
            seen.add(key)
            key = self.aliases[key]
        return key

    def get(self, key: Any, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(self.resolve(key) if isinstance(key, str) else key, default)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str) and not super().__contains__(key):
            key = self.resolve(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key) or (isinstance(key, str) and super().__contains__(self.resolve(key)))


def apply(ds: Any, rows: list[dict[str, Any]], file_name: str = MERGE_FILE_NAME) -> dict[str, Any]:
    """按归并表合并设备，返回统计。"""
    from backend.ontology.models import Provenance

    ds.equipment = AliasDict(ds.equipment)
    ds.parameters = AliasDict(ds.parameters)
    stats = {"file": file_name, "rows": len(rows), "applied": 0, "renamed": 0, "skipped": 0, "invalid": 0}

    for row in rows:
        if row.get("启用", "是") in ("否", "N", "n", "no", "No", "0"):
            stats["skipped"] += 1
            continue
        src_owl, dst_owl = row.get("原OWL Subject", ""), row.get("统一OWL Subject", "")
        new_name = row.get("统一设备名", "")
        src_id, dst_id = ds.equipment.resolve(ids.equipment_id(src_owl)), ds.equipment.resolve(ids.equipment_id(dst_owl))
        source = Provenance(file_name, SHEET, row.get("_row")).to_dict()
        if src_id not in ds.equipment or dst_id not in ds.equipment or not new_name:
            stats["invalid"] += 1
            ds.issues.append({
                "severity": "warning",
                "check": "设备归并表引用无效",
                "detail": f"第 {row.get('_row')} 行：{src_owl} → {dst_owl} 在点表中找不到，未归并。",
                "source": source,
            })
            continue
        dst = ds.equipment[dst_id]
        if src_id == dst_id:
            if dst["name"] != new_name:
                _add_alias(dst, dst, row, source, keep_record=False)
                dst["name"] = new_name
                stats["renamed"] += 1
            continue
        _merge(ds, ds.equipment[src_id], dst, row, source)
        dst["name"] = new_name
        stats["applied"] += 1

    # 名称统一后同步到点位、参数
    for equip in ds.equipment.values():
        for tid in equip["tagIds"]:
            tag = ds.tags.get(tid)
            if tag and tag.get("equipmentName") != equip["name"]:
                tag.setdefault("sourceEquipmentName", tag.get("equipmentName"))
                tag["equipmentName"] = equip["name"]
        for pid in equip["parameterIds"]:
            if pid in ds.parameters:
                ds.parameters[pid]["equipmentName"] = equip["name"]
    for entry in ds.stats_rows:
        if entry.get("equipmentId"):
            entry["equipmentId"] = ds.equipment.resolve(entry["equipmentId"])
    stats["equipmentAliases"] = len(ds.equipment.aliases)
    return stats


def _add_alias(dst: dict[str, Any], src: dict[str, Any], row: dict[str, Any], source: dict[str, Any], keep_record: bool = True) -> None:
    dst.setdefault("aliases", []).append({
        "id": src["id"],
        "name": src["name"],
        "owlSubject": src["owlSubject"],
        "station": src.get("station"),
        "tagCount": len(src["tagIds"]),
        "mergeKind": row.get("归并方式") if keep_record else KIND_RENAME,
        "rule": row.get("规则"),
        "basis": row.get("依据"),
        "source": source,
    })


def _merge(ds: Any, src: dict[str, Any], dst: dict[str, Any], row: dict[str, Any], source: dict[str, Any]) -> None:
    prefix = row.get("参数前缀", "")
    _add_alias(dst, src, row, source)
    for alias in src.get("aliases", []):
        dst["aliases"].append(alias)

    # 点位
    for tid in src["tagIds"]:
        tag = ds.tags.get(tid)
        if tag:
            tag.setdefault("sourceEquipmentName", tag.get("equipmentName"))
            tag.setdefault("sourceOwlSubject", tag.get("owlSubject"))
            tag["equipmentId"] = dst["id"]
            tag["owlSubject"] = dst["owlSubject"]
        if tid not in dst["tagIds"]:
            dst["tagIds"].append(tid)

    # 参数：带后缀的附属点位加前缀区分（RB进料阀指令）；同名参数合并（两支 pH 电极 → 一个 pH 参数）
    for pid in list(src["parameterIds"]):
        param = ds.parameters.get(pid)
        if not param:
            continue
        name = param["name"] if not prefix or param["name"].startswith(prefix) else prefix + param["name"]
        new_pid = ids.parameter_id(dst["owlSubject"], name)
        if new_pid in dict.keys(ds.parameters) and new_pid != pid:
            target = ds.parameters[new_pid]
            for key in ("categories", "units", "blockTypes", "tagIds"):
                for v in param.get(key, []):
                    if v not in target[key]:
                        target[key].append(v)
            target.setdefault("sourceParameterIds", []).append(pid)
            dict.__delitem__(ds.parameters, pid)
        else:
            dict.__delitem__(ds.parameters, pid)
            param.setdefault("sourceParameterIds", []).append(pid)
            param.update({"id": new_pid, "name": name, "equipmentId": dst["id"], "owlSubject": dst["owlSubject"]})
            dict.__setitem__(ds.parameters, new_pid, param)
            target = param
        if new_pid != pid:
            ds.parameters.aliases[pid] = new_pid
        for tid in target["tagIds"]:
            tag = ds.tags.get(tid)
            if tag and tag.get("parameterId") in (pid, new_pid):
                tag["parameterId"] = new_pid
                tag["parameterName"] = name
        if new_pid not in dst["parameterIds"]:
            dst["parameterIds"].append(new_pid)
        for area in ds.areas.values():
            if pid in area["parameterIds"]:
                area["parameterIds"] = [new_pid if p == pid else p for p in area["parameterIds"]]
                area["parameterIds"] = list(dict.fromkeys(area["parameterIds"]))

    # 统计、工段、控制站
    for k, v in src["stats"].items():
        dst["stats"][k] = dst["stats"].get(k, 0) + v
    if src.get("statsFromSheet1"):
        base = dst.get("statsFromSheet1") or {k: 0 for k in src["statsFromSheet1"]}
        dst["statsFromSheet1"] = {k: (base.get(k) or 0) + (v or 0) for k, v in src["statsFromSheet1"].items()}
    for aid, code in zip(src["areaIds"], src["areaCodes"]):
        if aid not in dst["areaIds"]:
            dst["areaIds"].append(aid)
            dst["areaCodes"].append(code)
    stations = dst.setdefault("stations", [dst.get("station")] if dst.get("station") else [])
    for st in src.get("stations") or [src.get("station")]:
        if st and st not in stations:
            stations.append(st)

    # 设备组、工段里的引用
    for group in ds.equipment_groups.values():
        if src["id"] in group["equipmentIds"]:
            group["equipmentIds"] = [e for e in group["equipmentIds"] if e != src["id"]]
            if dst["id"] not in group["equipmentIds"]:
                group["equipmentIds"].append(dst["id"])
    for area in ds.areas.values():
        if src["id"] in area["equipmentIds"]:
            area["equipmentIds"] = [dst["id"] if e == src["id"] else e for e in area["equipmentIds"]]

    dict.__delitem__(ds.equipment, src["id"])
    ds.equipment.aliases[src["id"]] = dst["id"]
