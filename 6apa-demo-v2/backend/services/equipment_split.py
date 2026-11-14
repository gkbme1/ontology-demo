"""设备拆分：把点表里「好几台设备共用一个名字」的合集拆回声明的实例。

DCS 点表按位号描述前缀切设备，「滤液泵a启停指令」「滤液泵b故障」……都被切到「滤液泵」名下，
于是一个叫「滤液泵」的设备挂着 6 台泵的 30 个点，而设备主数据声明的实例是 滤液泵A～F。
它与 equipment_merge（一台设备被写成多个名字）正好相反。

propose_split(ds) 按规则给出逐个位号的拆分表（写在 6APA_设备归并.xlsx 的「设备拆分」工作表），
apply_split(ds, rows) 加载时按表把位号移到对应实例上。规则（从严不从宽）：

- 只拆名字恰好是该组实例通名的设备：「滤液泵」之于 滤液泵A～F；
  组里的「丁酯泵a/b」不会被拆给 丁酯罐A/B；
- 台号取自位号描述里单独出现的字母（「滤液泵a启停指令」「出口控制阀c指令」）或序号
  （「液位泵1启动」→ 第 1 台）；
- 同一描述模板（去掉台号后相同的写法）的台号必须正好覆盖全部声明实例才拆：
  「脱色罐出口控制阀a～f」六个阀对六台罐，拆；「脱色罐出料泵a/b」两台泵对六台罐，
  说明是共用泵，不拆，留作组公共点位；冷凝器分阀 a～e 对四台冷凝器，对不上，不拆；
- 只有两台实例时，台号挂在「泵」上的不拆（「丁酯罐泵后出口控制阀A/B」可能指两台泵）；
- 位号里的字母与描述里的台号不一致时以描述为准，并在依据里写明。
拆不出台号的点留在原设备上，原设备改称「…·公共点位」；全部拆完的原设备删除，
旧 ID 记在 ds.equipment_splits 里（资产档案会转到所属设备组）。
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from backend.ontology import identifiers as ids
from backend.ontology.models import Provenance
from backend.services.equipment_merge import GENERIC_NAMES, AliasDict, _norm, _split_instance

SPLIT_SHEET = "设备拆分"
SPLIT_COLUMNS = [
    "序号", "工段", "设备组", "原设备名", "控制站", "原OWL Subject", "位号", "位号描述",
    "拆分到", "实例OWL Subject", "参数名", "规则", "依据", "启用",
]
RESIDUAL_SUFFIX = "·公共点位"

NATURE_INSTANCE = "实例"
NATURE_SHARED = "组公共点位"
NATURE_COLLECTION = "合集·未拆分"
NATURE_GENERIC = "兜底归类"

_LETTER = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])(?![A-Za-z0-9])")
_DIGIT = re.compile(r"(?<![A-Za-z0-9])([1-9])(?![A-Za-z0-9])")
_TAG_LETTER = re.compile(r"\d{3,4}([A-Z])(?:_|$)")


def _instance_keys(instances: list[str]) -> tuple[str | None, dict[str, str]]:
    """实例的通名与台号：滤液泵A～F →（滤液泵, {A: 滤液泵A, …}）。台号取实例编号末尾的字母。"""
    bases, letters = set(), {}
    for inst in instances:
        base, code = _split_instance(inst)
        if not code or not code[-1].isalpha():
            return None, {}
        bases.add(_norm(base))
        letters[code[-1].upper()] = inst
    if len(bases) != 1 or len(letters) != len(instances):
        return None, {}
    return bases.pop(), letters


def _variants(desc: str) -> list[tuple[str, str, int, str]]:
    """描述里每个可能的台号位置 →（模板, 台号, 位置, 类型）。"""
    out = []
    for kind, pattern in (("字母", _LETTER), ("序号", _DIGIT)):
        for m in pattern.finditer(desc):
            out.append((desc[:m.start()] + "{}" + desc[m.end():], m.group(1).upper(), m.start(), kind))
    return out


def _pump_pair(tpl: str, name: str, count: int) -> bool:
    """「丁酯罐泵后出口控制阀A/B」：只有两台实例时，挂在泵上的 A/B 更可能指两台泵而不是两个罐。"""
    if count >= 3 or "泵" in name or not tpl.startswith(name):
        return False
    return "泵" in tpl[len(name):tpl.index("{}")]


def propose_split(ds: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in sorted(ds.equipment_groups.values(), key=lambda g: (g.get("areaCode") or "", g["name"])):
        instances = [i for i in group.get("instances") or [] if i]
        if len(instances) < 2:
            continue
        base, by_letter = _instance_keys(instances)
        if not base:
            continue
        ordinal = {str(i + 1): inst for i, inst in enumerate(instances)}
        full = set(by_letter)
        for eid in list(group["equipmentIds"]):
            equip = ds.equipment.get(eid)
            if not equip or equip.get("equipmentGroupId") != group["id"] or equip["name"] in GENERIC_NAMES:
                continue
            if _norm(equip["name"]) != base:
                continue
            tags = [ds.tags[t] for t in equip["tagIds"] if t in ds.tags]
            # 每个模板出现过哪些台号
            letters_of: dict[tuple[str, str], set[str]] = defaultdict(set)
            for tag in tags:
                for tpl, key, _pos, kind in _variants(tag.get("rawDescription") or ""):
                    letters_of[(tpl, kind)].add(key)
            valid = {k for k, v in letters_of.items()
                     if ((k[1] == "字母" and v == full) or (k[1] == "序号" and v == set(ordinal)))
                     and not _pump_pair(k[0], equip["name"], len(instances))}
            for tag in tags:
                desc = tag.get("rawDescription") or ""
                hits = [(tpl, key, pos, kind) for tpl, key, pos, kind in _variants(desc) if (tpl, kind) in valid]
                if len(hits) != 1:
                    continue  # 没有台号或有歧义：留作组公共点位
                tpl, key, pos, kind = hits[0]
                inst = by_letter[key] if kind == "字母" else ordinal[key]
                target = next((ds.equipment[x] for x in group["equipmentIds"]
                               if x in ds.equipment and ds.equipment[x]["name"] == inst), None)
                owl = target["owlSubject"] if target else f":Dev_{equip.get('station')}_{inst}"
                pname = _strip_key(tag.get("parameterName") or "", desc, pos) \
                    or re.sub(r"[（(].*?[）)]", "", tag.get("parameterType") or "") or tag.get("variableCategory") or "点位"
                count = len(letters_of[(tpl, kind)])
                if kind == "字母":
                    rule = "描述台号"
                    basis = f"描述「{tpl.format('□')}」的台号 {''.join(sorted(letters_of[(tpl, kind)]))} 正好对应 {count} 台实例"
                else:
                    rule = "序号对应"
                    basis = f"描述「{tpl.format('□')}」的序号 1～{count} 按声明顺序对应 {count} 台实例（推断）"
                m = _TAG_LETTER.search(tag["name"])
                if kind == "字母" and m and m.group(1) != key:
                    basis += f"；位号字母 {m.group(1)} 与描述台号 {key} 不一致，按描述"
                rows.append({
                    "工段": equip.get("areaCode") or "",
                    "设备组": group["name"],
                    "原设备名": equip["name"],
                    "控制站": equip.get("station") or "",
                    "原OWL Subject": equip["owlSubject"],
                    "位号": tag["name"],
                    "位号描述": desc,
                    "拆分到": inst,
                    "实例OWL Subject": owl,
                    "参数名": pname,
                    "规则": rule,
                    "依据": basis,
                    "启用": "是",
                })
    for i, row in enumerate(rows, 1):
        row["序号"] = i
    return rows


def _strip_key(pname: str, desc: str, pos: int) -> str:
    """参数名里去掉台号：描述以参数名结尾时按同一位置去掉，否则原样保留。"""
    if pname and desc.endswith(pname):
        at = pos - (len(desc) - len(pname))
        if 0 <= at < len(pname):
            return pname[:at] + pname[at + 1:]
    return pname


# --------------------------------------------------------------------- 应用


def apply_split(ds: Any, rows: list[dict[str, Any]], file_name: str) -> dict[str, Any]:
    from backend.services.dcs_loader import _bump_stats

    if not isinstance(ds.equipment, AliasDict):
        ds.equipment = AliasDict(ds.equipment)
    if not isinstance(ds.parameters, AliasDict):
        ds.parameters = AliasDict(ds.parameters)
    ds.equipment_splits = {}
    stats = {"file": file_name, "sheet": SPLIT_SHEET, "rows": len(rows), "applied": 0, "skipped": 0,
             "invalid": 0, "instancesCreated": 0, "sourcesRemoved": 0}
    touched: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("启用", "是") in ("否", "N", "n", "no", "No", "0"):
            stats["skipped"] += 1
            continue
        src = ds.equipment.get(ids.equipment_id(row.get("原OWL Subject", "")))
        tag = ds.tags.get(ids.tag_id(row.get("位号", "")))
        inst_name, owl = row.get("拆分到", ""), row.get("实例OWL Subject", "")
        source = Provenance(file_name, SPLIT_SHEET, row.get("_row")).to_dict()
        if not src or not tag or tag["id"] not in src["tagIds"] or not inst_name or not owl:
            stats["invalid"] += 1
            ds.issues.append({"severity": "warning", "check": "设备拆分表引用无效",
                              "detail": f"第 {row.get('_row')} 行：{row.get('位号')} 不在 {row.get('原OWL Subject')} 上，未拆分。",
                              "source": source})
            continue
        dst = ds.equipment.get(ids.equipment_id(owl))
        if dst is None:
            dst = _new_instance(ds, src, inst_name, owl, source)
            stats["instancesCreated"] += 1
        if not any(a.get("id") == src["id"] for a in dst.get("aliases", [])):
            dst.setdefault("aliases", []).append({
                "id": src["id"], "name": src["name"], "owlSubject": src["owlSubject"], "station": src.get("station"),
                "tagCount": 0, "mergeKind": "拆分来源", "rule": row.get("规则"), "basis": row.get("依据"), "source": source,
            })
        alias = next(a for a in dst["aliases"] if a.get("id") == src["id"])
        alias["tagCount"] += 1
        _move_tag(ds, tag, src, dst, row.get("参数名") or tag.get("parameterName") or "")
        touched[src["id"]] = src
        touched[dst["id"]] = dst
        stats["applied"] += 1

    for equip in touched.values():
        equip["stats"] = {"total": 0, "pv": 0, "op": 0, "mot": 0, "val": 0, "dido": 0}
        for tid in equip["tagIds"]:
            equip["stats"]["total"] += 1
            _bump_stats(equip["stats"], ds.tags[tid].get("parameterType"))
        equip["tagCount"] = len(equip["tagIds"])

    for src in [e for e in touched.values() if e.get("splitInto")]:
        src["splitInto"] = sorted(src["splitInto"])
        group = ds.equipment_groups.get(src.get("equipmentGroupId") or "")
        if src["tagIds"]:
            # 拆不出台号的点留作设备组的公共点位
            src.setdefault("aliases", []).append({
                "id": src["id"], "name": src["name"], "owlSubject": src["owlSubject"], "station": src.get("station"),
                "tagCount": len(src["tagIds"]), "mergeKind": "统一名称", "rule": "组公共点位",
                "basis": "拆分后剩下的点没有台号，属于整组共用", "source": None,
            })
            src["name"] = (group["name"] if group else src["name"]) + RESIDUAL_SUFFIX
            src["splitResidual"] = True
            continue
        ds.equipment_splits[src["id"]] = {"name": src["name"], "owlSubject": src["owlSubject"],
                                          "groupId": src.get("equipmentGroupId"), "instanceIds": sorted(src["splitInto"])}
        for g in ds.equipment_groups.values():
            g["equipmentIds"] = [e for e in g["equipmentIds"] if e != src["id"]]
        for area in ds.areas.values():
            area["equipmentIds"] = [e for e in area["equipmentIds"] if e != src["id"]]
        for pid in src["parameterIds"]:
            if dict.__contains__(ds.parameters, pid):
                dict.__delitem__(ds.parameters, pid)
        dict.__delitem__(ds.equipment, src["id"])
        stats["sourcesRemoved"] += 1
    return stats


def _new_instance(ds: Any, src: dict[str, Any], name: str, owl: str, source: dict[str, Any]) -> dict[str, Any]:
    eid = ids.equipment_id(owl)
    equip = {
        "id": eid, "owlSubject": owl, "name": name,
        "areaId": src["areaId"], "areaName": src.get("areaName"), "areaCode": src.get("areaCode"),
        "areaIds": [src["areaId"]], "areaCodes": [src.get("areaCode")],
        "station": src.get("station"), "parameterIds": [], "tagIds": [],
        "stats": {"total": 0, "pv": 0, "op": 0, "mot": 0, "val": 0, "dido": 0},
        "statsFromSheet1": None, "overview": None,
        "equipmentGroup": src.get("equipmentGroup"), "equipmentGroupId": src.get("equipmentGroupId"),
        "confidence": src.get("confidence"), "sourceType": src.get("sourceType"), "source": source,
    }
    dict.__setitem__(ds.equipment, eid, equip)
    group = ds.equipment_groups.get(src.get("equipmentGroupId") or "")
    if group and eid not in group["equipmentIds"]:
        group["equipmentIds"].append(eid)
    area = ds.areas.get(src["areaId"])
    if area and eid not in area["equipmentIds"]:
        area["equipmentIds"].append(eid)
    return equip


def _move_tag(ds: Any, tag: dict[str, Any], src: dict[str, Any], dst: dict[str, Any], pname: str) -> None:
    src["tagIds"].remove(tag["id"])
    dst["tagIds"].append(tag["id"])
    src.setdefault("splitInto", set()).add(dst["id"])
    tag.setdefault("sourceEquipmentName", tag.get("equipmentName"))
    tag.setdefault("sourceOwlSubject", tag.get("owlSubject"))
    tag.update({"equipmentId": dst["id"], "equipmentName": dst["name"], "owlSubject": dst["owlSubject"]})

    old_pid = tag.get("parameterId")
    old = ds.parameters.get(old_pid) if old_pid else None
    if not pname:
        return
    new_pid = ids.parameter_id(dst["owlSubject"], pname)
    param = ds.parameters.get(new_pid) if dict.__contains__(ds.parameters, new_pid) else None
    if param is None:
        param = {
            "id": new_pid, "name": pname, "equipmentId": dst["id"], "equipmentName": dst["name"],
            "owlSubject": dst["owlSubject"], "areaId": dst["areaId"], "areaName": dst.get("areaName"),
            "areaCode": dst.get("areaCode"), "station": dst.get("station"),
            "categories": list((old or {}).get("categories", [])), "units": list((old or {}).get("units", [])),
            "blockTypes": list((old or {}).get("blockTypes", [])), "tagIds": [],
            "sourceType": (old or {}).get("sourceType"), "source": (old or {}).get("source"),
            "sourceParameterIds": [],
        }
        dict.__setitem__(ds.parameters, new_pid, param)
        dst["parameterIds"].append(new_pid)
        area = ds.areas.get(dst["areaId"])
        if area and new_pid not in area["parameterIds"]:
            area["parameterIds"].append(new_pid)
    param["tagIds"].append(tag["id"])
    if old:
        for key in ("categories", "units", "blockTypes"):
            for v in old.get(key, []):
                if v not in param[key]:
                    param[key].append(v)
        if old_pid not in param.setdefault("sourceParameterIds", []):
            param["sourceParameterIds"].append(old_pid)
        if tag["id"] in old["tagIds"]:
            old["tagIds"].remove(tag["id"])
        if not old["tagIds"]:
            # 旧参数的点全部移走：旧参数 ID 转到新参数
            dict.__delitem__(ds.parameters, old_pid)
            ds.parameters.aliases[old_pid] = new_pid
            src["parameterIds"] = [p for p in src["parameterIds"] if p != old_pid]
            for area in ds.areas.values():
                if old_pid in area["parameterIds"]:
                    area["parameterIds"] = [p for p in area["parameterIds"] if p != old_pid]
    tag["parameterId"] = new_pid
    tag["parameterName"] = pname


# --------------------------------------------------------------------- 性质


def classify(ds: Any) -> dict[str, int]:
    """给每个设备标上性质：实例 / 组公共点位 / 合集·未拆分 / 兜底归类。"""
    bases = {}
    for g in ds.equipment_groups.values():
        instances = [i for i in g.get("instances") or [] if i]
        if len(instances) >= 2:
            names = {_norm(_split_instance(i)[0]) for i in instances}
            if len(names) == 1:
                bases[g["id"]] = (names.pop(), set(instances))
    counts: dict[str, int] = defaultdict(int)
    for equip in ds.equipment.values():
        if equip["name"] in GENERIC_NAMES:
            nature = NATURE_GENERIC
        elif equip.get("splitResidual"):
            nature = NATURE_SHARED
        elif equip.get("equipmentGroupId") in bases and _norm(equip["name"]) == bases[equip["equipmentGroupId"]][0] \
                and equip["name"] not in bases[equip["equipmentGroupId"]][1]:
            nature = NATURE_COLLECTION
        else:
            nature = NATURE_INSTANCE
        equip["nature"] = nature
        counts[nature] += 1
    return dict(counts)
